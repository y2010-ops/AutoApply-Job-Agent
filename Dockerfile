# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Create a non-root user to run the app (Required by Hugging Face Spaces)
RUN useradd -m -u 1000 user
USER user

# Set environment variables for the user and Python
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface

# Set the working directory
WORKDIR $HOME/app

# Copy the requirements file
COPY --chown=user requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir --user -r requirements.txt

# Pre-download the SentenceTransformer model to bake it into the Docker image
# This prevents downloading ~80MB every time the Hugging Face Space starts up
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy the rest of the application code
COPY --chown=user . .

# Hugging Face Spaces expose port 7860 by default
EXPOSE 7860

# Command to run the FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
