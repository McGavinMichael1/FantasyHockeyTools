# Fantasy Hockey Add/Drop Analyzer - Project Plan

## Project Overview
**Goal:** Build an ML-powered tool to analyze fantasy hockey free agents and help make add/drop decisions based on projected future value for your specific league's scoring system.

**Key Principle:** Real hockey performance ≠ Fantasy hockey value for your league

**Your Learning Goals:**
- Practice Python project structure and organization
- Work with real-world APIs and messy data
- Apply ML concepts from coursework to a practical problem
- Debug dimensional consistency issues hands-on
- Build something end-to-end from scratch

---

## Project Flow (High-Level)

```
START
  ↓
[1. Data Collection] ← Fetch NHL stats via API
  ↓
[2. Fantasy Point Calculation] ← Apply your league's scoring rules
  ↓
[3. Data Storage & Management] ← Save historical data for training
  ↓
[4. Feature Engineering] ← Create meaningful predictors
  ↓
[5. Model Building] ← Train ML models for predictions
  ↓
[6. Prediction & Recommendations] ← Generate add/drop suggestions
  ↓
[7. UI/Output] ← Display results in usable format
  ↓
END
```

---

## Phase Breakdown

### Phase 0: Project Setup & Planning
**Status:** [ ] Not Started | [ ] In Progress | [ ] Complete

**Tasks:**
- [ ] Create project directory structure
- [ ] Set up version control (git)
- [ ] Create virtual environment
- [ ] Initialize `requirements.txt`
- [ ] Document your league's scoring rules

**Deliverable:** Working development environment

**Questions to Explore:**
1. What folder structure makes sense for separating data, source code, and models?
2. Which Python version should you use?
3. What dependencies might you need? (Think about: API calls, data manipulation, ML, visualization)

**Your Notes:**
```
[Space for your decisions and discoveries]
```

---

### Phase 1: Data Collection (API Integration)
**Status:** [ ] Not Started | [x] In Progress | [ ] Complete

**Objective:** Successfully fetch NHL player statistics from a free API

**Tasks:**
- [ ] Research available NHL APIs (see conversation hints)
- [ ] Explore API endpoints using browser dev tools
- [ ] Write functions to fetch player stats
- [ ] Handle API errors and edge cases
- [ ] Test with a few sample players

**Key Technical Challenges:**
- How do you make HTTP requests in Python?
- How do you parse JSON responses?
- What happens if the API is down or rate-limits you?
- Which endpoints give you the stats you need?

**Guiding Questions:**
1. What player statistics are available through the API?
2. How is the data structured (JSON format, nested objects)?
3. How often do you need to fetch fresh data?
4. Do you need current season only or historical data too?
5. What's the difference between player stats and team stats?

**File Structure Hint:**
```
Probably need: nhl_api.py or data_fetcher.py
```

**Your Notes & Discoveries:**
- API: NHLE (api-web.nhle.com/v1/) — free, no auth required
- Stats endpoint works but doesn't flag active/inactive players
- Must fetch rosters from all 32 teams and use as an active-player filter
- Modules created: nhl_api.py (API calls), data_processor.py (DataFrame logic), main.py (orchestration)
- Caching strategy TBD — consider saving raw JSON responses to avoid hitting API repeatedly during dev

---

### Phase 2: Fantasy Points Calculation
**Status:** [ ] Not Started | [ ] In Progress | [ ] Complete

**Objective:** Convert real NHL stats into fantasy points based on YOUR league's scoring system

**Tasks:**
- [ ] Document your league's scoring rules clearly
- [ ] Write a function to calculate fantasy points from player stats
- [ ] Validate calculations against your actual league results
- [ ] Handle edge cases (missing stats, games played, etc.)

**Key Technical Challenges:**
- How do you map API stat names to your league's categories?
- How do you handle per-game vs. total stats?
- What about players who change teams mid-season?

**Critical Thinking:**
1. What stats does your league count? (Goals, assists, PPP, SOG, hits, blocks, etc.)
2. What's the point value for each stat category?
3. Are there position-specific scoring differences?
4. Do you need to account for games played?
5. Should you calculate total points or points-per-game?

**Your League Scoring Rules:**
```
[Fill in your league's scoring here - this is CRITICAL for the whole project]

Example format:
Goals (G): X points
Assists (A): X points
Power Play Points (PPP): X points
Shots on Goal (SOG): X points
...
```

**Your Notes:**
```
[How did you implement the calculation?]
[Any tricky edge cases?]
```

---

### Phase 3: Data Storage & Historical Tracking
**Status:** [ ] Not Started | [ ] In Progress | [ ] Complete

**Objective:** Build a system to store and update player stats over time for ML training

**Tasks:**
- [ ] Decide on storage format (CSV, SQLite, JSON?)
- [ ] Create schema/structure for storing player data
- [ ] Write functions to save fetched data
- [ ] Write functions to load historical data
- [ ] Implement update logic (avoid duplicates, handle new data)

**Key Decisions:**
1. Where will data live? (Local files, database?)
2. How will you organize it? (One file per player? One file per date? One big file?)
3. How often will you update it?
4. What's your data retention policy?

**Data Structure Questions:**
- What fields/columns do you need to store?
- Do you need player metadata (position, team, age)?
- How do you uniquely identify players?
- How do you track date/time of data collection?

**Your Notes:**
```
[Storage decision and reasoning:]
[Data schema:]
[Update frequency plan:]
```

---

### Phase 4: Feature Engineering
**Status:** [ ] Not Started | [ ] In Progress | [ ] Complete

**Objective:** Create meaningful features that predict FUTURE fantasy performance

**This is where ML gets interesting - and where you'll learn the most!**

**Tasks:**
- [ ] Brainstorm potential features
- [ ] Calculate rolling averages (last 7 days, 14 days, 30 days)
- [ ] Create trend features (improving vs. declining)
- [ ] Add contextual features (ice time, PP usage, linemates)
- [ ] Handle missing data
- [ ] Normalize/scale features appropriately

**Critical Thinking:**
1. What patterns might predict future performance?
   - Recent hot streaks?
   - Consistent performers?
   - Changes in ice time or role?
   - Strength of upcoming schedule?

2. What's the difference between:
   - Features that explain past performance (easy)
   - Features that predict future performance (hard!)

3. How do you avoid data leakage?

**Feature Ideas to Explore:**
- [ ] Points per game (last N games)
- [ ] Shooting percentage trends
- [ ] Ice time trends
- [ ] Power play opportunity changes
- [ ] Recent linemate quality
- [ ] Home vs. away splits
- [ ] Days rest between games
- [ ] Opponent strength

**Matrix Dimension Practice:**
This is where you'll encounter those dimensional consistency issues you mentioned!

Questions to work through:
- If you have N players and M features, what shape is your feature matrix?
- How do you handle players with different numbers of games played?
- What do you do with missing values in your feature matrix?

**Your Notes:**
```
[Features you created:]
[Dimensionality challenges you faced:]
[How you solved them:]
```

---

### Phase 5: Model Building & Training
**Status:** [ ] Not Started | [ ] In Progress | [ ] Complete

**Objective:** Train ML models to predict player fantasy value

**Tasks:**
- [ ] Define your prediction target (what are you predicting?)
- [ ] Split data into train/validation/test sets
- [ ] Start with simple baseline model
- [ ] Implement multiple model types
- [ ] Tune hyperparameters
- [ ] Evaluate model performance
- [ ] Compare models

**Key Decisions:**

**What are you predicting?**
- Next week's fantasy points?
- Rest of season total points?
- Probability of being a top performer?
- Something else?

**Model Progression (Start Simple!):**
1. Baseline: Use recent average (no ML)
2. Linear Regression: Simple, interpretable
3. Random Forest: Handles non-linearity
4. Gradient Boosting: Often best performance
5. Neural Network: Practice from your course (if you want)

**Evaluation Questions:**
1. How do you measure success? (MAE, RMSE, R²?)
2. Are you more concerned with ranking players correctly or exact point predictions?
3. How do you prevent overfitting to past performance?
4. What's your validation strategy?

**Dimensional Debugging Practice:**
This is where you'll really practice those matrix operations!
- Input shape to model?
- Output shape from model?
- Batch processing considerations?
- How do predictions align back to player names?

**Your Notes:**
```
[Target variable definition:]
[Models tried:]
[Performance metrics:]
[Best model and why:]
[Dimensional issues encountered and solved:]
```

---

### Phase 6: Prediction & Recommendation System
**Status:** [ ] Not Started | [ ] In Progress | [ ] Complete

**Objective:** Use trained model to generate actionable add/drop recommendations

**Tasks:**
- [ ] Fetch current free agent list
- [ ] Generate predictions for all available players
- [ ] Rank players by projected value
- [ ] Compare to your current roster
- [ ] Generate add/drop recommendations
- [ ] Add confidence intervals or uncertainty estimates

**Logic to Implement:**
1. Who are the free agents in your league?
2. What's their projected value vs. your worst roster player?
3. Should you consider positional needs?
4. How confident is the model in each prediction?

**Your Notes:**
```
[Recommendation logic:]
[How you handle uncertainty:]
```

---

### Phase 7: User Interface
**Status:** [ ] Not Started | [ ] In Progress | [ ] Complete

**Objective:** Make the tool actually usable for yourself

**Options (Pick One to Start):**

**Option A: Command Line Interface (Simplest)**
- Run: `python main.py`
- Outputs recommendations to terminal
- Can save to text file

**Option B: Streamlit Web App (Local)**
- Runs on localhost
- Nice visual interface
- No hosting needed
- Good for data/ML projects

**Option C: Desktop GUI**
- More complex
- Standalone app

**Recommended:** Start with A, upgrade to B if you want it prettier

**Tasks:**
- [ ] Design output format
- [ ] Implement chosen UI
- [ ] Add filtering/sorting options
- [ ] Make it easy to update data and re-run

**Your Notes:**
```
[UI choice and reasoning:]
[Features implemented:]
```

---

## Project Milestones & Checkpoints

### Milestone 1: Data Pipeline Working
**Definition of Done:**
- Can fetch player stats from API
- Can calculate fantasy points
- Can save data locally
- Have at least 30 days of historical data

### Milestone 2: Basic ML Model
**Definition of Done:**
- Feature engineering implemented
- At least one model trained
- Can generate predictions
- Have evaluated performance

### Milestone 3: MVP Complete
**Definition of Done:**
- Can input current free agents
- Generates ranked recommendations
- Usable interface (even if basic)
- Actually helps you make decisions!

### Milestone 4: Refinement
**Definition of Done:**
- Multiple models compared
- Better features added
- UI polished
- Deployed for regular use

---

## Technical Debt & Future Enhancements

**Keep track of "I'll come back to this later" items:**

- [ ] 
- [ ] 
- [ ] 

**Ideas for V2.0:**
- Trade analyzer
- Lineup optimizer
- Injury impact predictor
- Schedule difficulty analysis
- Keeper value calculator

---

## Learning Log

### Date: March 2026
**What I learned:**
- Separation of concerns: keep API calls (nhl_api.py), data processing (data_processor.py), and orchestration (main.py) in separate modules
- The NHLE stats endpoint does NOT indicate whether a player is currently active — must cross-reference with roster data from all 32 teams
- Claude Code (VS Code) and Claude.ai Projects do NOT share session history — use PROJECT-PLAN.md as the shared memory layer, referenced with @PROJECT-PLAN.md in Claude Code

**Challenges faced:**
- Stats endpoint alone is insufficient to determine active player status
- Combining multiple API responses into a clean DataFrame requires careful handling of nested JSON

**Solutions found:**
- Fetch rosters from all teams to build an "active players" filter, then join with stats data
- Use pandas DataFrames as the core data structure for manipulation

**Questions for next time:**
- Where should caching live — in nhl_api.py or as a separate module?
- Should cache be per-endpoint or per-player?

## Resources & References

## Resources & References

**APIs Found:**
- NHLE API (unofficial): https://api-web.nhle.com/v1/
- Key endpoints:
  - Skater stats: `/v1/skater-stats-leaders/current`
  - Team roster: `/v1/roster/{teamAbbrev}/current`

**Libraries Being Used:**
- `requests` — HTTP calls to NHLE API
- `pandas` — DataFrame creation and manipulation
- `json` — parsing API responses

**Helpful Documentation:**
- NHLE API community docs: https://gitlab.com/dword4/nhlapi

---

## Current Phase
**I am currently working on:** Phase 1 - Data Collection

**Next immediate task:**
- [ ] Complete DataFrame creation from JSON responses in data_processor.py
- [ ] Combine roster + stats endpoints to filter for active players only
- [ ] Implement basic caching to avoid redundant API calls during development

**Blocked on:**
- Nothing currently

---

## Success Criteria

**How will you know this project is successful?**

1. Technical goals:
   - [ ] 
   - [ ] 

2. Learning goals:
   - [ ] 
   - [ ] 

3. Practical goals:
   - [ ] Actually helps me win my fantasy league!
   - [ ] 

---

**Remember:** This is a learning project. It's okay if your first version isn't perfect. The goal is to practice, make mistakes, debug, and learn. You're building real skills by working through real problems!

**When stuck:** Try things, break things, google errors, ask specific questions. That's how you learn.

**When frustrated:** Step back, tackle smaller pieces, review what you've learned so far.

You've got this! 🏒
