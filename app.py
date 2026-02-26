from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from models import db
from routes import register_routes

def create_app():
    app = Flask(__name__)
    
    app.secret_key = 'super_secret_stagecraft_key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stagecraft.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
    
    register_routes(app)
    
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)