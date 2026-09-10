def validate_fields(data, required_fields):
    missing = [f for f in required_fields if f not in data or not data[f]]
    if missing:
        return False, f"Missing fields: {', '.join(missing)}"
    return True, None 