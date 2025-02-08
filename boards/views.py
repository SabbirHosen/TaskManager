import redis
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Case, Q, When
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.module_loading import import_string
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from config.utils.redis_handler import redis_client
from projects.models import Project, ProjectMembership
from projects.permissions import (IsProjectAdminOrMemberReadOnly,
                                  IsProjectMember)
from rest_framework import generics, permissions, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Attachment, Board, Comment, Item, Label, List, Notification
from .permissions import CanViewBoard, IsAuthorOrReadOnly
from .serializers import (AttachmentSerializer, BoardSerializer,
                          CommentSerializer, ItemSerializer, LabelSerializer,
                          ListSerializer, NotificationSerializer,
                          ShortBoardSerializer, ItemUpdateSerializer, CommentCreateSerializer, LabelCreateSerializer)

r = redis_client

User = get_user_model()


class BoardList(generics.ListCreateAPIView):
    serializer_class = ShortBoardSerializer
    permission_classes = [IsAuthenticated, IsProjectMember]

    def get_project(self, pk):
        project = get_object_or_404(Project, pk=pk)
        self.check_object_permissions(self.request, project)
        return project

    def get_queryset(self, *args, **kwargs):
        project_id = self.request.GET.get('project', None)
        sort = self.request.GET.get('sort', None)
        search = self.request.GET.get('q', None)

        if sort == "recent":
            redis_key = f'{self.request.user.email}:RecentlyViewedBoards'
            board_ids = r.zrange(redis_key, 0, 3, desc=True)

            preserved = Case(*[When(pk=pk, then=pos)
                               for pos, pk in enumerate(board_ids)])
            return Board.objects.filter(pk__in=board_ids).order_by(preserved)

        if project_id is None:
            project_ids = ProjectMembership.objects.filter(
                member=self.request.user).values_list('project__id', flat=True)
            queryset = Board.objects.filter(
                Q(owner_id=self.request.user.id, owner_model=ContentType.objects.get(model='customuser')) |
                Q(owner_id__in=project_ids, owner_model=ContentType.objects.get(model='project')))
        else:
            queryset = Board.objects.filter(
                owner_id=project_id, owner_model=ContentType.objects.get(model='project'))
            project = self.get_project(project_id)

        if search is not None:
            return queryset.filter(title__icontains=search)[:2]
        return queryset.order_by('title')

    @extend_schema(
        request=ShortBoardSerializer,
        responses={201: ShortBoardSerializer},
        parameters=[
            OpenApiParameter(
                name="project",
                type=OpenApiTypes.STR,
                description="Filter boards by project ID"
            ),
            OpenApiParameter(
                name="sort",
                type=OpenApiTypes.STR,
                description="Sort boards (e.g., 'recent')"
            ),
            OpenApiParameter(
                name="q",
                type=OpenApiTypes.STR,
                description="Search for boards by title"
            ),
        ],
        examples=[
            OpenApiExample(
                "Create Board Example",
                description="Example payload for creating a board",
                value={
                    "title": "New Board",
                    "project": "1"
                },
                request_only=True  # This is only for request payloads
            )
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Create a new board",
        description="Creates a new board for the authenticated user or for a specific project if provided.",
        request=ShortBoardSerializer,
        responses={
            201: OpenApiResponse(response=ShortBoardSerializer, description="Board created successfully"),
            400: OpenApiResponse(description="Validation error"),
        },
        examples=[
            OpenApiExample(
                name="Board Example",
                value={
                    "project": 1234,
                    "title": "My Board",
                    "image": None,
                    "image_url": None,
                    "color": "FFFFFF"
                },
                description="An example of a valid request body",
                request_only=True  # Ensures this example is for request payloads
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        serializer = ShortBoardSerializer(
            data=request.data, context={"request": request})
        print(f"Serializer is valid: {serializer.is_valid()}")
        print(f"Serializer errors: {serializer.errors}")
        print(f"requested data: {request.data}")
        if serializer.is_valid():
            if 'project' in request.data.keys():
                project = self.get_project(request.data['project'])
                serializer.save(
                    owner_id=project.id, owner_model=ContentType.objects.get(model='project'))
            else:
                print(f"owner_id: {request.user.id}, owner_model: {ContentType.objects.get(model='customuser')}")
                serializer.save(owner_id=request.user.id,
                                owner_model=ContentType.objects.get(model='customuser'))
            print(f"Serializer is valid: {serializer.data}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BoardDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BoardSerializer
    permission_classes = [CanViewBoard]

    def get_queryset(self, *args, **kwargs):
        project_ids = ProjectMembership.objects.filter(
            member=self.request.user).values_list('project__id', flat=True)
        return Board.objects.filter(
            Q(owner_id=self.request.user.id, owner_model=ContentType.objects.get(model='customuser')) |
            Q(owner_id__in=project_ids, owner_model=ContentType.objects.get(model='project')))

    def get_object(self):
        board_id = self.kwargs.get('pk')
        redis_key = f'{self.request.user.email}:RecentlyViewedBoards'
        cur_time_int = int(timezone.now().strftime("%Y%m%d%H%M%S"))
        r.zadd(redis_key, {board_id: cur_time_int})
        return super().get_object()

    def perform_update(self, serializer):
        # When you update, you may pass in a new image/image_url/color
        # If an image is passed, we need to clear the existing background - image_url/color
        # and so on
        req_data = self.request.data

        if "image" in req_data:
            serializer.save(image_url="", color="")
        elif "image_url" in req_data:
            serializer.save(image=None, color="")
        elif "color" in req_data:
            serializer.save(image=None, image_url="")


class BoardStar(APIView):
    permission_classes = [CanViewBoard]

    def get_board(self, pk):
        board = get_object_or_404(Board, pk=pk)
        self.check_object_permissions(self.request, board)
        return board

    def post(self, request, *args, **kwargs):
        if 'board' in request.data.keys():
            board_id = request.data['board']
        else:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        board = self.get_board(board_id)

        if request.user.starred_boards.filter(pk=board.pk).exists():
            request.user.starred_boards.remove(board)
        else:
            request.user.starred_boards.add(board)

        return Response(status=status.HTTP_204_NO_CONTENT)


class ListShow(generics.ListCreateAPIView):
    serializer_class = ListSerializer
    permission_classes = [CanViewBoard]

    def get_board(self, pk):
        board = get_object_or_404(Board, pk=pk)
        self.check_object_permissions(self.request, board)
        return board

    def get_queryset(self, *args, **kwargs):
        board_id = self.request.GET.get('board', None)
        board = self.get_board(board_id)
        return List.objects.filter(board=board).order_by('order')

    @extend_schema(
        summary="Get lists for a board",
        description="Retrieve all lists that belong to a specific board. The `board` query parameter is required.",
        parameters=[
            OpenApiParameter(
                name="board",
                description="The ID of the board whose lists you want to retrieve",
                required=True,
                type=int,
                location=OpenApiParameter.QUERY
            )
        ],
        responses={
            200: OpenApiResponse(response=ListSerializer(many=True), description="Lists retrieved successfully"),
            400: OpenApiResponse(description="Missing `board` query parameter"),
            403: OpenApiResponse(description="Permission denied"),
        }
    )
    def get(self, request, *args, **kwargs):
        board_id = self.request.GET.get('board', None)

        if board_id is None:
            return Response({"error": "Missing 'board' query parameter"}, status=status.HTTP_400_BAD_REQUEST)

        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Create a new list",
        description="Creates a new list for a given board. The `board` field is required in the request body.",
        request=ListSerializer,
        responses={
            201: OpenApiResponse(response=ListSerializer, description="List created successfully"),
            400: OpenApiResponse(description="Missing `board` field in request body"),
            403: OpenApiResponse(description="Permission denied"),
        },
        examples=[
            OpenApiExample(
                name="Valid Request",
                value={
                    "title": "My List",
                    "board": 1,
                    'order': 1,
                },
                description="Example of a valid request to create a list",
                request_only=True
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        if 'board' in request.data.keys():
            board = self.get_board(request.data['board'])
            return super().post(request, *args, **kwargs)
        return Response({"error": "Missing 'board' field in request body"}, status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        board = self.get_board(self.request.data['board'])
        serializer.save(board=board)


class ListDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ListSerializer
    permission_classes = [CanViewBoard]

    def get_object(self):
        pk = self.kwargs.get('pk')
        list = get_object_or_404(List, pk=pk)
        self.check_object_permissions(self.request, list.board)
        return list


class ItemList(generics.ListCreateAPIView):
    serializer_class = ItemSerializer
    permission_classes = [CanViewBoard]

    def get_list(self, pk):
        list_obj = get_object_or_404(List, pk=pk)
        self.check_object_permissions(self.request, list_obj.board)
        return list_obj

    def get_queryset(self):
        list_id = self.request.GET.get('list')
        search = self.request.GET.get('q')

        if list_id:
            list_obj = self.get_list(list_id)
            return Item.objects.filter(list=list_obj).order_by('order')

        if search:
            project_ids = ProjectMembership.objects.filter(member=self.request.user).values_list('project__id',
                                                                                                 flat=True)
            boards = Board.objects.filter(
                Q(owner_id__in=project_ids, owner_model=ContentType.objects.get(model='project')) |
                Q(owner_id=self.request.user.id, owner_model=ContentType.objects.get(model='customuser'))
            )
            lists = List.objects.filter(board__in=boards)
            return Item.objects.filter(list__in=lists, title__icontains=search)[:2]

        return Item.objects.none()

    @extend_schema(
        summary="Retrieve items for a specific list",
        description="Fetches all items belonging to a given list. Requires `list` query parameter. Optionally, use `q` for search.",
        parameters=[
            OpenApiParameter(
                name="list",
                description="ID of the list whose items should be retrieved",
                required=False,
                type=int,
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name="q",
                description="Search items by title",
                required=False,
                type=str,
                location=OpenApiParameter.QUERY
            )
        ],
        responses={
            200: OpenApiResponse(response=ItemSerializer(many=True), description="List of items"),
            400: OpenApiResponse(description="Invalid request parameters")
        }
    )
    def get(self, request, *args, **kwargs):
        if not any(param in request.GET for param in ['list', 'q']):
            return Response({"error": "Either 'list' or 'q' parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Create a new item",
        description="Adds a new item to a specific list.",
        request=ItemSerializer,
        responses={
            201: OpenApiResponse(response=ItemSerializer, description="Item created"),
            400: OpenApiResponse(description="Invalid input data"),
        },
        examples=[
            OpenApiExample(
                name="Valid Item Creation",
                value={"title": "New Task", "list": 5},
                request_only=True,
                description="Creating an item in list with ID 5."
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        if 'list' not in request.data:
            return Response({"error": "'list' field is required"}, status=status.HTTP_400_BAD_REQUEST)
        return super().post(request, *args, **kwargs)

    def perform_create(self, serializer):
        list_obj = self.get_list(self.request.data['list'])
        serializer.save(list=list_obj)


class ItemDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ItemSerializer
    permission_classes = [CanViewBoard]

    def get_user(self, username, board):
        user = get_object_or_404(User, username=username)
        # Can this user view the board though?
        if user.can_view_board(board):
            return user
        return None

    def get_label(self, pk, board):
        label = get_object_or_404(Label, pk=pk)
        # Does this label belong to this item's board?
        if board == label.board:
            return label
        return None

    def get_list(self, pk, board):
        list = get_object_or_404(List, pk=pk)
        if board == list.board:
            return list
        return None

    def get_object(self):
        pk = self.kwargs.get('pk')
        item = get_object_or_404(Item, pk=pk)
        self.check_object_permissions(self.request, item.list.board)
        return item

    @extend_schema(
        request=ItemUpdateSerializer,
        responses={200: ItemSerializer},
        description="Update an item with new assignments, labels, list movement, or appearance."
    )
    def put(self, request, *args, **kwargs):
        item = self.get_object()
        if "assigned_to" in request.data:
            user = self.get_user(request.data["assigned_to"], item.list.board)
            if user is None:
                return Response({"assigned_to": ["This user cannot view this board"]},
                                status=status.HTTP_400_BAD_REQUEST)

        if "labels" in request.data:
            label = self.get_label(request.data["labels"], item.list.board)
            if label is None:
                return Response({"labels": ["This label doees not belong to this board"]},
                                status=status.HTTP_400_BAD_REQUEST)

        if "list" in request.data:
            list = self.get_list(request.data['list'], item.list.board)
            if list is None:
                return Response({'list': ["This list doesn't belong to this baord"]},
                                status=status.HTTP_400_BAD_REQUEST)

        return super().put(request, *args, **kwargs)

    def perform_update(self, serializer):
        # Same logic as BoardDetail
        req_data = self.request.data

        if "image" in req_data:
            item = serializer.save(image_url="", color="")
        elif "image_url" in req_data:
            item = serializer.save(image=None, color="")
        elif "color" in req_data:
            item = serializer.save(image=None, image_url="")
        else:
            item = serializer.save()

        # Assigning or removing someone?
        if "assigned_to" in req_data:
            user = self.get_user(req_data["assigned_to"], item.list.board)

            if item.assigned_to.filter(pk=user.pk).exists():
                item.assigned_to.remove(user)
            else:
                item.assigned_to.add(user)

        # Adding or removing a label?
        if "labels" in req_data:
            label = self.get_label(req_data["labels"], item.list.board)

            if item.labels.filter(pk=label.pk).exists():
                item.labels.remove(label)
            else:
                item.labels.add(label)

        if "list" in req_data:
            list = self.get_list(req_data["list"], item.list.board)
            serializer.save(list=list)


class CommentList(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [CanViewBoard]

    def get_item(self, pk):
        item = get_object_or_404(Item, pk=pk)
        self.check_object_permissions(self.request, item.list.board)
        return item

    def get_queryset(self, *args, **kwargs):

        item_id = self.request.GET.get('item', None)

        item = self.get_item(item_id)
        return Comment.objects.filter(item=item)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="item",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter comments by item ID."
            )
        ],
        responses={200: CommentSerializer(many=True)},
        description="Retrieve a list of comments for a specific item."
    )
    def get(self, request, *args, **kwargs):

        item_id = self.request.GET.get('item', None)

        if item_id is None:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=CommentCreateSerializer,
        responses={201: CommentSerializer},
        description="Create a new comment for a specific item."
    )
    def post(self, request, *args, **kwargs):
        if 'item' in request.data.keys():
            item = self.get_item(request.data['item'])
            return super().post(request, *args, **kwargs)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        item = self.get_item(self.request.data['item'])
        serializer.save(item=item, author=self.request.user)


class CommentDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CommentSerializer
    permission_classes = [IsAuthorOrReadOnly]

    def get_object(self):
        pk = self.kwargs.get('pk')
        comment = get_object_or_404(Comment, pk=pk)
        self.check_object_permissions(self.request, comment)
        return comment


class LabelList(generics.ListCreateAPIView):
    serializer_class = LabelSerializer
    permission_classes = [
        CanViewBoard
    ]

    def get_board(self, pk):
        board = get_object_or_404(Board, pk=pk)
        self.check_object_permissions(self.request, board)
        return board

    def get_queryset(self, *args, **kwargs):
        board_id = self.request.GET.get('board', None)

        board = self.get_board(board_id)
        return Label.objects.filter(board=board)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="board",
                type=int,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Filter labels by board ID."
            )
        ],
        responses={200: LabelSerializer(many=True)},
        description="Retrieve a list of labels for a specific board."
    )
    def get(self, request, *args, **kwargs):
        board_id = self.request.GET.get('board')

        if not board_id:
            return Response({"error": "Missing 'board' query parameter."}, status=status.HTTP_400_BAD_REQUEST)

        return super().get(request, *args, **kwargs)

    @extend_schema(
        request=LabelCreateSerializer,
        responses={201: LabelSerializer},
        description="Create a new label for a specific board."
    )
    def post(self, request, *args, **kwargs):
        if 'board' in request.data.keys():
            board = self.get_board(request.data['board'])
            return super().post(request, *args, **kwargs)
        return Response(status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        board = self.get_board(self.request.data['board'])
        serializer.save(board=board)


class LabelDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LabelSerializer
    permission_classes = [CanViewBoard]

    def get_object(self):
        pk = self.kwargs.get('pk')
        label = get_object_or_404(Label, pk=pk)
        self.check_object_permissions(self.request, label.board)
        return label


class LabelDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Label.objects.all()
    serializer_class = LabelSerializer
    permission_classes = [
        permissions.AllowAny
    ]


class AttachmentList(generics.ListCreateAPIView):
    queryset = Attachment.objects.all()
    serializer_class = AttachmentSerializer
    permission_classes = [
        permissions.AllowAny
    ]


class AttachmentDetail(generics.RetrieveUpdateDestroyAPIView):
    queryset = Attachment.objects.all()
    serializer_class = AttachmentSerializer
    permission_classes = [
        permissions.AllowAny
    ]


class NotificationList(APIView):
    def get(self, *args, **kwargs):
        notifications = Notification.objects.filter(
            recipient=self.request.user).order_by('-created_at')
        serializer = NotificationSerializer(notifications, many=True)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):  # Mark all as read
        Notification.objects.filter(
            recipient=self.request.user, unread=True).update(unread=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
