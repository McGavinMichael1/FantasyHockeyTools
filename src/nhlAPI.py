import requests
import json
import time

def getRosterData(team):
    url = f"https://api-web.nhle.com/v1/roster/{team}/current"
    while True:
        response = requests.get(url)
        if response.status_code == 429:
            print("Rate limited, waiting...")
            time.sleep(5)
            continue # retry
        elif response.status_code == 200:
            break
        else:
            print("unexpected error occured")
    print(f"Status code for {team}: {response.status_code}")  # Check if request succeeded
    print(f"Response text preview: {response.text[:200]}")    # See what's actually returned
    data = response.json()
    return data

def getTeamNames():
    # first call the standings endpoint to retrieve team abbreviations
    team_abbrev_list = []
    url = "https://api-web.nhle.com/v1/standings/now"
    response = requests.get(url)
    data = response.json()
    # append all team names to a dictionary
    for team in data['standings']:
        team_abbrev_list.append(team['teamAbbrev']['default'])
    return team_abbrev_list
