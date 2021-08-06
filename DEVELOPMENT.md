# terraform-operator

```
cd images/terraform-operator
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
kopf run ./terraform-operator.py --log-format ful
```
ps: make sure you only have one instance of this operator  running at the time

# ui

```
cd images/ui
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements.txt
USERS_FILE=users.json FLASK_APP=ui.py FLASK_ENV=development python3 -m flask run
```
