# Fantasy Hockey

Fantasy hockey analysis and prediction tools with ML models for player pickups and cooling detection.

## Setup

This project uses [uv](https://github.com/astral-sh/uv) for Python package management.

### Installation

1. Install uv if you haven't already:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   uv venv
   uv pip install -e .
   ```

3. (Optional) For GPU support with CUDA 12.8:
   ```bash
   uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
   ```

### Activating the Environment

```bash
# On macOS/Linux
source .venv/bin/activate

# On Windows
.venv\Scripts\activate
```

## Data Setup

Download MoneyPuck data from https://moneypuck.com/data.htm:

1. **Historical data**: "All Situations, 2008-2024" → Save as `data/raw/2008_to_2024.csv`
2. **Current season**: "All Situations, Current Season" → Save as `data/raw/moneypuck_current.csv`

**Yahoo API (Optional)**: To filter out rostered players, see [YAHOO_SETUP.md](YAHOO_SETUP.md)

## Usage

### Train Models
```bash
python main.py train-pickups
```

### Get Pickup Recommendations
```bash
python main.py pickups
```

**Note**: First run may take 30-60 seconds to process features. Subsequent runs use cached data (< 1 second).

### Run Streamlit UI
```bash
streamlit run ui/app.py
```

## Project Structure

- `main.py` - CLI entry point for training and predictions
- `src/` - Core functionality
  - `dataProcessing.py` - NHL API data fetching and processing
  - `fantasyPoints.py` - Fantasy points calculations
  - `moneypuck.py` - MoneyPuck data handling
  - `yahooAPI.py` - Yahoo Fantasy API integration
  - `features/` - Feature engineering for ML models
  - `models/` - ML model training and prediction
- `ui/` - Streamlit web interface
- `tests/` - Unit tests
- `data/` - Local data cache (gitignored)
- `models/` - Saved trained models

## Development

### Running Tests
```bash
uv run pytest
```

### Adding Dependencies
```bash
uv add package-name
```

### Updating Dependencies
```bash
uv pip compile pyproject.toml -o requirements.txt
uv pip sync requirements.txt
```
