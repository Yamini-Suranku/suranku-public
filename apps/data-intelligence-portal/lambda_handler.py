"""AWS Lambda entrypoint — wraps the FastAPI app (frontend + API) with Mangum.

Used only on Lambda (see Dockerfile.lambda + template.yaml). The same app runs
unchanged via uvicorn/Docker elsewhere. Lambda's filesystem is read-only except
/tmp, so the image sets PORTAL_DATA_DIR=/tmp/... (ephemeral demo storage).
"""
from mangum import Mangum

from backend.app.main import app

handler = Mangum(app)
