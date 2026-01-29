import pandas as pd
import numpy as np
import json

def makeTeamDataframe(jsonData):
    forwards = jsonData['forwards']
    defensemen = jsonData['defensemen']
    goalies = jsonData['goalies']
    roster_dict = forwards + defensemen + goalies
    df = pd.DataFrame(roster_dict)
    return df