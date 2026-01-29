from src import nhlAPI
from src import dataProcessing
def main():
    """Main entry point for the fantasy hockey application."""
    print("Welcome to Fantasy Hockey!")

    # Your code here
    team = "TOR"
    torontoData = nhlAPI.getRosterData(team)
    # print(torontoData['forwards'])
    df = dataProcessing.makeTeamDataframe(torontoData)
    print(df.head())
    print(df.columns)


if __name__ == "__main__":
    main()
