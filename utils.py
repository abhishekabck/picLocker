

def verify_db(db):
    if not db.is_connected():
        raise Exception("Database connection is closed.")