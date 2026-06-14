# Open Grondwaterkaart

Full-stack web application built with Django + Django REST Framework (backend) and Angular + Angular Material (frontend).

## Setup

### Backend

```bash
virtualenv --python=python3.12 env
source env/bin/activate
pip install -r requirements.txt
cp config/settings_local.py.example config/settings_local.py
# Edit config/settings_local.py as needed
python manage.py migrate
python manage.py runserver
```

### Frontend

```bash
cd client
npm install
npm start
```

The Angular dev server runs on [http://localhost:4200](http://localhost:4200) and proxies `/api` requests to the Django backend on port 8000.
