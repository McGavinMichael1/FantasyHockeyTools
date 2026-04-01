def calculateSkaterPoints(stats):
    points = 0
    points += stats.get('goals', 0) * 3
    points += stats.get('assists', 0) * 2
    points += stats.get('plusMinus', 0) * 0.5
    points += stats.get('gameWinningGoals', 0) * 1
    points += stats.get('powerPlayPoints', 0) * 1
    points += stats.get('shorthandedPoints', 0) * 1
    points += stats.get('shots', 0) * 0.15
    return points