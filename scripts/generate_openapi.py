"""
Dumps the FastAPI app's OpenAPI schema to openapi.json.

Run this whenever routers/schemas change, then regenerate mobile-side
TypeScript types from it:

    python scripts/generate_openapi.py
    cd ../paisaera-mobile && npm run generate:types

This is the "FastAPI → OpenAPI → openapi-typescript → React Native"
pipeline from the review — the mobile app's src/types/generated.ts should
never be hand-edited, only regenerated.
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app

if __name__ == "__main__":
    schema = app.openapi()
    output_path = os.path.join(os.path.dirname(__file__), "..", "openapi.json")
    with open(output_path, "w") as f:
        json.dump(schema, f, indent=2)
    print(f"Wrote OpenAPI schema to {output_path}")
