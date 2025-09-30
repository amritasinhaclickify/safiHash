import re

def is_valid_national_id(id_number: str) -> bool:
    """
    Basic African national ID format validation
    Example: GH123456, NG654321
    """
    pattern = r'^[A-Z]{2}\d{6}$'
    return bool(re.match(pattern, id_number))

def verify_document(data: dict) -> dict:
    """
    Validates national ID, name, and date of birth format.
    Always returns consistent structure to avoid internal errors.
    """
    errors = []

    if 'name' not in data or not data['name'].strip():
        errors.append("Name is required.")

    if 'national_id' not in data or not is_valid_national_id(data['national_id']):
        errors.append("Invalid national ID format (e.g., GH123456).")

    if 'dob' not in data or not re.match(r'^\d{4}-\d{2}-\d{2}$', data['dob']):
        errors.append("Date of birth must be in yyyy-mm-dd format.")

    if errors:
        return {
            "status": "failed",
            "message": "KYC verification failed.",
            "errors": errors
        }

    return {
        "status": "pending",
        "message": "KYC data looks valid. Pending admin approval.",
        "errors": []
    }


