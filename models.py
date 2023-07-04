from flask_sqlalchemy import SQLAlchemy

db=SQLAlchemy()

class Users(db.Model):
    __tablename__ ='users'
    id              =db.Column(db.Integer, primary_key=True, autoincrement=True)
    email            =db.Column(db.String(40))
    password          =db.Column(db.String(80))
    available          =db.Column(db.String(5))
    # def __init__(self,email,password):
    #     self.email=email
    #     self.password=password
    #     self.available='N'