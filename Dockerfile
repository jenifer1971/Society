FROM nikolaik/python-nodejs:python3.11-nodejs20

# Trust all PyPI/PyTorch hosts — required when a TLS-intercepting proxy is in use
RUN pip config set global.trusted-host \
    "pypi.org files.pythonhosted.org pypi.python.org download.pytorch.org"

# Install uv (used only to export the lockfile; actual install done via pip)
RUN pip install uv

WORKDIR /app

COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

# Install Node deps
RUN npm ci && npm ci --prefix frontend

# Export locked Python deps, drop nvidia CUDA packages (not needed without a GPU).
# torch itself installs fine from PyPI and runs on CPU without nvidia-* packages.
RUN cd backend && \
    uv export --frozen --no-dev --no-hashes --no-emit-project \
        | grep -Ev '^(nvidia-|triton)' > /tmp/requirements.txt && \
    pip install -r /tmp/requirements.txt && \
    pip install -e .

COPY . .

EXPOSE 3000 5001
CMD ["npm", "run", "dev"]
