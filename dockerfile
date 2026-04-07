# Use a lightweight Python base
FROM python:3.11-slim

# Install system dependencies for Ansible and SSH
RUN apt-get update && apt-get install -y \
    ssh \
    sshpass \
    curl \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
# We explicitly install core dependencies for the automation scripts
# then attempt to install from requirements.txt if it exists
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir requests python-dotenv ansible && \
    if [ -s requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Copy the entire project
COPY . .

# Ensure scripts are executable for the Linux environment inside Docker
RUN chmod +x /app/create.sh \
    && chmod +x /app/setup.sh \
    && chmod +x /app/scripts/*.sh \
    && chmod +x /app/scripts/*.py

# Start with a bash shell
CMD ["/bin/bash"]