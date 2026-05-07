FROM nikolaik/python-nodejs:python3.11-nodejs20

# Trust all PyPI/PyTorch hosts — required when a TLS-intercepting proxy is in use
RUN pip config set global.trusted-host \
    "pypi.org files.pythonhosted.org pypi.python.org download.pytorch.org"

# Install uv (used only to export the lockfile; actual install done via pip)
RUN pip install uv

WORKDIR /app

COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/requirements.txt /tmp/requirements.txt
COPY backend/pyproject.toml ./backend/

# Install Node deps
RUN npm ci && npm ci --prefix frontend

# Install pinned Python deps (nvidia/triton already excluded in requirements.txt).
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    pip install --no-cache-dir -e backend/ && \
    pip cache purge

COPY . .

EXPOSE 3000 5001
CMD ["npm", "run", "dev"]
