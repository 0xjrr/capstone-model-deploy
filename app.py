import os
import json
import pickle
import joblib
import pandas as pd
from flask import Flask, jsonify, request
from peewee import (
    Model, IntegerField, FloatField,
    TextField, IntegrityError
)
from playhouse.shortcuts import model_to_dict
from playhouse.db_url import connect


########################################
# Begin database stuff

# The connect function checks if there is a DATABASE_URL env var.
# If it exists, it uses it to connect to a remote postgres db.
# Otherwise, it connects to a local sqlite db stored in predictions.db.
DB = connect(os.environ.get('DATABASE_URL') or 'sqlite:///predictions.db')

class Prediction(Model):
    observation_id = TextField(unique=True)
    observation = TextField()
    prediction = FloatField()
    proba = FloatField()
    true_class = IntegerField(null=True)

    class Meta:
        database = DB


DB.create_tables([Prediction], safe=True)

# End database stuff
########################################

########################################
# Unpickle the previously-trained model

PATH_TO_MODEL = 'model'

with open(os.path.join(PATH_TO_MODEL, 'columns.json')) as fh:
    columns = json.load(fh)

pipeline = joblib.load(os.path.join(PATH_TO_MODEL, 'pipeline.pickle'))

with open(os.path.join(PATH_TO_MODEL, 'dtypes.pickle'), 'rb') as fh:
    dtypes = pickle.load(fh)


# End model un-pickling
########################################

########################################
# Begin field verification
def verify_data_types(data):
    expected_types = {
        "observation_id": [str],
        "Type": [str],
        "Date": [str],
        "Part of a policing operation": [bool],
        "Latitude": [float, int],
        "Longitude": [float, int],
        "Gender": [str],
        "Age range": [str],
        "Officer-defined ethnicity": [str],
        "Legislation": [str],
        "Object of search": [str],
        "station": [str]
    }
    for col, expected_type in expected_types.items():
        if col not in data:
            return (True, {'error': f"{col} column not found"})
        actual_type = type(data[col])
        if actual_type not in expected_type:
            return (True, {'error': f"{col} column has wrong data type. Expected {expected_type}, got {actual_type}"})
    return (False, "All data types are correct")

# End field verification
########################################

########################################
# Begin webserver stuff

app = Flask(__name__)


@app.route('/should_search', methods=['POST'])
def predict():
    # Flask provides a deserialization convenience function called
    # get_json that will work if the mimetype is application/json.
    obs_dict = request.get_json()

    is_error, error_msg = verify_data_types(obs_dict)
    if is_error:
        response = {'error': error_msg}
        return jsonify(response)
    
    _id = obs_dict['observation_id']
    observation = obs_dict
    # Now do what we already learned in the notebooks about how to transform
    # a single observation into a dataframe that will work with a pipeline.
    obs = pd.DataFrame([observation], columns=columns).astype(dtypes)
    # Now get ourselves an actual prediction of the positive class.
    proba = pipeline.predict_proba(obs)[0, 1]
    prediction = pipeline.predict(obs)
    response = {'outcome': bool(prediction)}
    
    p = Prediction(
        observation_id=_id,
        proba=proba,
        prediction= prediction,
        observation=request.data
    )

    try:
        p.save()
    except IntegrityError:
        error_msg = 'Observation ID: "{}" already exists'.format(_id)
        response['error'] = error_msg
        print(error_msg)
        DB.rollback()
    return jsonify(response)


@app.route('/search_result', methods=['POST'])
def update():
    obs = request.get_json()
    try:
        p = Prediction.get(Prediction.observation_id == obs['observation_id'])
        p.true_class = obs['outcome']
        p.save()
        return jsonify(
                {
                    "observation_id": p.observation_id,
                    "outcome": p.true_class,
                    "predicted_outcome": p.prediction
                }
            )
    except Prediction.DoesNotExist:
        error_msg = 'Observation ID: "{}" does not exist'.format(obs['id'])
        return jsonify({'error': error_msg})
    except:
        error_msg = 'error malformed request'
        return jsonify({'error': error_msg})


@app.route('/list-db-contents')
def list_db_contents():
    return jsonify([
        model_to_dict(obs) for obs in Prediction.select()
    ])


# End webserver stuff
########################################

if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True, port=5000)
