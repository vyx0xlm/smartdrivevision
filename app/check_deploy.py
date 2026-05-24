#!/usr/bin/env python3
"""Run on PythonAnywhere Bash console to diagnose deployment issues."""

import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
print('=== SmartDrive deploy check ===')
print('Python:', sys.version)
print('App dir:', APP_DIR)
print('CWD:', os.getcwd())
print()

required = [
    'app.py',
    'data_store.py',
    'firebase_service.py',
    'requirements.txt',
    'templates/login.html',
]
print('Files:')
for name in required:
    path = os.path.join(APP_DIR, name)
    print(f'  {"OK" if os.path.isfile(path) else "MISSING"}  {name}')

secrets = ['.env', 'serviceAccountKey.json', 'firebase_web_config.json']
print('\nSecrets (needed for Google sign-in):')
for name in secrets:
    path = os.path.join(APP_DIR, name)
    print(f'  {"OK" if os.path.isfile(path) else "MISSING"}  {name}')

print('\nImports:')
try:
    import flask
    print('  OK  flask', flask.__version__)
except Exception as e:
    print('  FAIL flask:', e)

try:
    import flask_cors
    print('  OK  flask-cors')
except Exception as e:
    print('  FAIL flask-cors:', e)

try:
    import flask_login
    print('  OK  flask-login')
except Exception as e:
    print('  FAIL flask-login:', e)

try:
    import dotenv
    print('  OK  python-dotenv')
except Exception as e:
    print('  FAIL python-dotenv:', e)

try:
    import firebase_admin
    print('  OK  firebase-admin')
except Exception as e:
    print('  FAIL firebase-admin:', e)

print('\nLoad Flask app:')
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(APP_DIR, '.env'))
    from app import app, init_db
    print('  OK  imported app')
    init_db()
    print('  OK  init_db()')
    with app.test_client() as client:
        r = client.get('/login')
        print(f'  OK  GET /login -> {r.status_code}')
except Exception as e:
    print('  FAIL:', type(e).__name__, e)
    import traceback
    traceback.print_exc()

print('\nDone.')
