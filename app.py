from __future__ import print_function

from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
import pandasql as ps
from google_auth_oauthlib.flow import InstalledAppFlow,Flow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import pickle

from flask import Flask, request, jsonify,render_template, abort
from flask_cors import CORS
import requests
import os
import time

import openai
import json

from functools import wraps
import jwt
from email_validator import validate_email, EmailNotValidError
from models import db, Users

with open('config.json', 'r') as f:
    config = json.load(f)

openai.api_key = config['api_key']
os.environ["OPENAI_API_KEY"] = config['api_key']
SECRET_KEY = config['SECRET_KEY']

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"]='sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
app.app_context().push()
db.create_all()
CORS(app)

index = None

# here enter the id of your google sheet
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def validate_email_and_password(email, password):
    try:
        if email == "" or password == "" or len(password) < 6:
            return False
        else :
            validate_email(email)
            return True
    except EmailNotValidError as e:
        # Email is not valid.
        # The exception message is human-readable.
        return False

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            token = request.headers["Authorization"].split(" ")[1]
        if not token:
            return {
                "message": "Authentication Token is missing!",
                "data": None,
                "error": "Unauthorized"
            }, 401
        try:
            data=jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = Users.query.filter_by(id=data["user_id"]).first()
            if current_user is None:
                return {
                "message": "Invalid Authentication token!",
                "data": None,
                "error": "Unauthorized"
            }, 401

            if current_user.available == 0:
                return {
                "message": "Invalid Authentication token!",
                "data": None,
                "error": "Unauthorized"
            }, 401
        except Exception as e:
            return {
                "message": "Something went wrong",
                "data": None,
                "error": str(e)
            }, 500

        return f(current_user, *args, **kwargs)

    return decorated

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data:
            return {
                "message": "Please provide user details",
                "data": None,
                "error": "Bad request"
            }, 400
        # validate input
        is_validated = validate_email_and_password(data.get('email'), data.get('password'))
        if is_validated is not True:
            return dict(message='Invalid data', data=None, error=is_validated), 400
        user = Users.query.filter_by(email=data.get('email'), password=data.get('password')).first()
        if user:
            try:
                # token should expire after 24 hrs
                if user.available == '0':
                    return {
                        "message": "Invalid Authentication token!",
                        "data": None,
                        "error": "Unauthorized"
                    }
                user_obj = {"id":user.id, "email":user.email}
                user_obj["token"] = jwt.encode(
                    {
                        "user_id": user.id,
                        "available": user.available
                    },
                    SECRET_KEY,
                    algorithm="HS256"
                )
                return {
                    "message": "Successfully fetched auth token",
                    "data": user_obj
                }
            except Exception as e:
                return {
                    "error": "Something went wrong",
                    "message": str(e)
                }, 500
        return {
            "message": "Error fetching auth token!, invalid email or password",
            "data": None,
            "error": "Unauthorized"
        }, 404
    except Exception as e:
        return {
                "message": "Something went wrong!",
                "error": str(e),
                "data": None
        }, 500

@app.route("/api/users", methods=["POST"])
@token_required
def users(user):
    try:
        if user.email != "admin@wantable.com" :
            return jsonify({"admin":False, "users":[]})
        users = db.session.query(Users).filter(Users.email != "admin@wantable.com")
        arr_users = []
        for reg_user in users:
            arr_users.append({"id":reg_user.id, "email":reg_user.email, "available":reg_user.available})
        return jsonify({"admin":user.email == "admin@wantable.com", "users": arr_users})
    except Exception as e:
        return {
            "message": "Something went wrong",
            "error": str(e),
            "data": None
        }, 500

@app.route("/api/updateuser", methods=["POST"])
@token_required
def updateuser(user):
    data = request.get_json()
    try:
        if user.email != "admin@wantable.com" :
            return jsonify([])
        user = Users.query.filter_by(id=data["id"]).first()
        if user.available=="1":
            user.available = "0"
        else:
            user.available = "1"
        db.session.merge(user)
        db.session.commit()
        return jsonify({"isSuccess":"ok"})
    except Exception as e:
        return {
            "message": "Something went wrong",
            "error": str(e),
            "data": None
        }, 500
        

@app.route("/api/register", methods=["POST"])
def register():
    try:
        data = request.get_json()
        print(data)
        if not data:
            return {
                "message": "Please provide user details",
                "data": None,
                "error": "Bad request"
            }, 400
        is_validated = validate_email_and_password(data.get('email'), data.get('password')) and data.get('password') == data.get('confirm_password')
        if is_validated is not True:
            return dict(message='Invalid data', data=None, error=is_validated), 400
        user = Users.query.filter_by(email=data.get('email')).first()
        if user:
            return {
                "message": "User already exists",
                "error": "Conflict",
                "data": None
            }, 409
        adding_user = Users(email=data.get('email'), password=data.get('password'), available=0)
        db.session.add(adding_user)
        db.session.commit()
        return {
            "message": "Successfully created new user",
            "isSuccess": "ok"
        }, 201
    except Exception as e:
        return {
            "message": "Something went wrong",
            "error": str(e),
            "data": None
        }, 500

@app.route('/api/document_headers', methods=['POST'])
@token_required
def document_headers(user):
    query_data = request.get_json()
    sheetId = query_data['sheetId']
    RANGE_NAME = '!A1:FF1000'
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'secret.json', SCOPES) # here enter the name of your downloaded JSON file
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()
    sheet_metadata = sheet.get(spreadsheetId=sheetId).execute()
    sheets = sheet_metadata.get('sheets', '')
    RANGE_NAME = sheets[0]['properties']['title'] + RANGE_NAME
    
    result_input = sheet.values().get(spreadsheetId=sheetId,
                                range=RANGE_NAME).execute()
    values_input = result_input.get('values', [])
    
    return jsonify(values_input[0])

@app.route('/api/main', methods=['POST'])
@token_required
def main(user):
    messages = []
    textMessage = ""
    IsTable = 1
    IsText = 1
    query_data = request.get_json()
    query = query_data['query']
    print(query)
    sheetId = query_data['sheetId']
    data = ""
    SAMPLE_RANGE_NAME = '!A1:FF1000'

    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'secret.json', SCOPES) # here enter the name of your downloaded JSON file
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('sheets', 'v4', credentials=creds)

    # Call the Sheets API
    sheet = service.spreadsheets()
    sheet_metadata = sheet.get(spreadsheetId=sheetId).execute()
    sheets = sheet_metadata.get('sheets', '')
    SAMPLE_RANGE_NAME = sheets[0]['properties']['title'] + SAMPLE_RANGE_NAME
    
    result_input = sheet.values().get(spreadsheetId=sheetId,
                                range=SAMPLE_RANGE_NAME).execute()
    values_input = result_input.get('values', [])
    
    nonBlackArray = []
    for i in values_input[0]:
        if i == "" : nonBlackArray.append("Image")
        else : nonBlackArray.append(i)

    df_query = pd.DataFrame(values_input[1:], columns=nonBlackArray)
    
    # df.to_csv("named.csv");

    ai_model = "gpt-3.5-turbo"
    system_msg = "sql"
    messages.append({"role": "system", "content": system_msg})
    messages.append({"role": "user", "content": "Hello"})
    # print("Step1 Completed")

    table_string = "My table name is df_query. i have a table with " + str(len(df_query.columns)) + " columns. Columns names are "
    for col in df_query.columns:
        table_string = table_string + col + ", "
    
    messages.append({"role": "user", "content": table_string})
    messages.append({"role": "assistant", "content": "Okay, what would you like to do with this table? Does it need to be modified, queried, or something else?"})
    print("Step2 Completed")
    
    user_prompt = "I will type queries and you will reply with what the terminal would show. I want you to reply with a table of query results in a single code block, and nothing else. Do not write explanations. Do not type commands unless I instruct you to do so. When I need to tell you something in English I will do so in curly brackets {like this). Table column header might have spaces Do not write explanations. Rate must be expressed like 50 not 0.5. For example 50% is 50. Do not type commands unless I instruct you to do so. " + query + " Write a sqlite sql query about above question."

    try :
        messages.append({"role": "user", "content": user_prompt})
        response = openai.ChatCompletion.create(
        model=ai_model,
        messages=messages
        )
        reply = response["choices"][0]["message"]["content"]
        messages.append({"role": "assistant", "content": reply})
    except : 
        IsTable = 0

    
    tbl_str = ""

    replyMsg = reply[reply.find('SELECT'):reply.find('``',reply.find('SELECT')-1)]
    print(replyMsg)
    try :
        data = ps.sqldf(replyMsg, locals())
        print(data)
        for col in data.columns:
            tbl_str += col + ","                                
    except :
        IsTable = 0
    
    try :
        response = openai.ChatCompletion.create(
        model=ai_model,
        messages=[{"role": "user", "content": query + " Please explain about this table : " + data.to_string()}])
        textMessage = response["choices"][0]["message"]["content"]
    except : 
        IsText = 0      
    print(IsTable)

    if IsText == 1 and IsTable == 1 :
        return jsonify({"response" : textMessage, "tablecdata":tbl_str, "tablerdata": data.to_json(orient='values') })
    elif IsText == 1 and IsTable == 0:
        return jsonify({"response" : textMessage, "tablecdata":"", "tablerdata": "[]" })
    elif IsText == 0 and IsTable == 1: 
        return jsonify({"response" : "", "tablecdata":tbl_str, "tablerdata": data.to_json(orient='values') })
    else :
        return jsonify({"response" : "I'm sorry,I don't understand what you're trying to say. Can you please rephrase your question or provide more context so I can better assist you?", "tablecdata":"", "tablerdata": "[]" })

@app.route('/api/documents', methods=['POST'])
@token_required
def documents(user):
    SCOPES = ['https://www.googleapis.com/auth/drive']
    SERVICE_ACCOUNT_FILE = "./key.json"
    credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('drive', 'v3', credentials=credentials)

    topFolderId = '1dNkyLrW71NEmsYivHK8CxcLsrJ0qDd3c' # Please set the folder of the top folder ID.

    items = []
    pageToken = ""
    while pageToken is not None:
        response = service.files().list(q="'" + topFolderId + "' in parents", pageSize=1000, pageToken=pageToken, fields="nextPageToken, files(id, name)").execute()
        items.extend(response.get('files', []))
        pageToken = response.get('nextPageToken')

    return jsonify(items)


if __name__ == '__main__':
    app.run('',8000)