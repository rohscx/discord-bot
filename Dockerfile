# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Install ping (iputils-ping) package
RUN apt-get update && apt-get install -y iputils-ping && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app's source code into the container
COPY . .

# Expose the port (not necessary for Discord bots but good practice)
EXPOSE 8080

# Set the environment variable for Python to run in unbuffered mode
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "lounge_bot.py"]

