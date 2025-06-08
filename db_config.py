import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",           # default for XAMPP
        password="",           # leave empty unless set
        database="bloodbank_db"
    )
