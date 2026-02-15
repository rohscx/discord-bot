# Environment Variables

Set the following environment variables:

```bash
DISCORD_BOT_TOKEN=your_discord_bot_token_here
TEXT_CHANNEL_ID=your_text_channel_id_here
TIME_THRESHOLD=7200  # Adjust threshold as needed (in seconds)
```

Copy `.env.example` to `.env` and fill in your actual values.

---

# Synology AWS ECR Setup Guide

## Step 1: Get the AWS ECR Authentication Token

Run the following command on your local machine (with AWS CLI installed):

```bash
aws ecr get-login-password --region <your-region>
```

For example:

```bash
aws ecr get-login-password --region us-east-1
```

The command will output a long token string. **Copy this token**—it will serve as the **password**.

---

## Step 2: Build and Push the Docker Image to AWS ECR

### 1. Configure AWS CLI (on your local machine):

```bash
aws configure
```
You’ll be prompted for:
- **AWS Access Key ID**
- **AWS Secret Access Key**
- **Region** (e.g., `us-east-1`)
- **Output format** (leave default or choose your preference)

---

### 2. Create an ECR Repository

```bash
aws ecr create-repository --repository-name discord-bot
```

---

### 3. Authenticate Docker to AWS ECR

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <your-aws-account-id>.dkr.ecr.us-east-1.amazonaws.com
```

---

### 4. Build the Docker Image

```bash
docker buildx build --platform linux/amd64 -t <your-aws-account-id>.dkr.ecr.us-east-1.amazonaws.com/discord-bot .
```

---

### 5. Push the Image to AWS ECR

```bash
docker push <your-aws-account-id>.dkr.ecr.us-east-1.amazonaws.com/discord-bot:latest
```

Once the image is pushed, you can use the Synology NAS to pull and deploy the image as needed.

---

## Step 3: Configure Synology NAS Docker Registry

On your Synology NAS Docker settings:

- **Registry Name:** Set it to something meaningful, like **AWS ECR**.
- **Registry URL:** Use the correct format:

  ```
  https://<aws_account_id>.dkr.ecr.<region>.amazonaws.com
  ```

  **Example:**

  ```
  https://<your-aws-account-id>.dkr.ecr.us-east-1.amazonaws.com
  ```

- **Username:** Set it to **AWS** (required for AWS ECR).
- **Password:** Paste the token you copied from **Step 1**.
- **SSL:** Check **Trust SSL Self-Signed Certificate** if applicable, or leave unchecked if using a trusted certificate.

---

## Step 4: Test the Connection

Click **Apply**, then try pulling a container image from the AWS ECR using the Synology NAS Docker interface.

**Example image URL:**

```
aws_account_id.dkr.ecr.<region>.amazonaws.com/your-repository:your-tag
```

---

# Docker Hub and Local Deployment on Synology NAS
  
## Build and Push Docker Image to Docker Hub

```bash
docker buildx build --platform linux/amd64 -t <your-dockerhub-username>/discord-bot-image .
docker push <your-dockerhub-username>/discord-bot-image
```

# Google Cloud Deployment (For Reference Only, Does Not Work Due to Cloud Run Timeouts and Idling)

## Build and Push Docker Image to Google Cloud

```bash
docker build -t discord-bot-image . &\
docker buildx build --platform linux/amd64 -t discord-bot-image .
```

Tag and push the image:

```bash
docker tag discord-bot-image gcr.io/<your-gcp-project-id>/discord-bot-image &\
docker push gcr.io/<your-gcp-project-id>/discord-bot-image
```

## Run Locally

```bash
docker run -e DISCORD_BOT_TOKEN='<Place_Token_here>' -p 8080:8080 discord-bot-image
```

## Deploy to Google Cloud Run

```bash
gcloud run deploy discord-bot-service \
  --image gcr.io/<your-gcp-project-id>/discord-bot-image \
  --platform managed \
  --region us-east1 \
  --no-allow-unauthenticated \
  --memory 512Mi \
  --set-env-vars DISCORD_BOT_TOKEN=<your_discord_bot_token> \
  --timeout 300
```

---

