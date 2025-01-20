import hashlib


def calculate_file_hash(file_path: str) -> str:
    """Calculate the SHA-256 hash of the file content."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as file:
        while chunk := file.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()
