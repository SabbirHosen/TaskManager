# Use the official Python image from the Docker Hub
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /usr/src/app

# Install dependencies
COPY requirements.txt /usr/src/app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy project
COPY . /usr/src/app/

# Run the development server
CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py makemigrations && python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
