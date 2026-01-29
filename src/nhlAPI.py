import requests
import json

def getRosterData(team):
    url = f"https://api-web.nhle.com/v1/roster/{team}/current"
    response = requests.get(url)
    data = response.json()
    return data