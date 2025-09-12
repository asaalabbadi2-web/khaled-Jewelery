# Flask app setup, database connection, and register routes

# Flask app setup with PostgreSQL, db init, register routes, create tables, run debug
from flask import Flask
from models import db
from routes import api
import os

app = Flask(__name__)
# Configure PostgreSQL connection (replace values as needed)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/yasar_db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
app.register_blueprint(api)

@app.before_first_request
def create_tables():
	db.create_all()

if __name__ == "__main__":
	app.run(debug=True)
