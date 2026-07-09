import pandas as pd

from src.features.shared import select_matrix


def _frame():
    # Two feature columns, one label column, one column that is neither.
    return pd.DataFrame({
        'feat_a': [1.0, 2.0, 3.0],
        'feat_b': [4.0, 5.0, 6.0],
        'target': [0.1, 0.2, 0.3],
        'name': ['a', 'b', 'c'],
    })


def test_select_matrix_returns_only_allowlisted_feature_columns():
    df = _frame()
    X, y = select_matrix(df, ['feat_a', 'feat_b'], 'target')
    # X carries exactly the named features, in order -- 'name' is not on the
    # allowlist so it must be absent even though it's in the frame.
    assert list(X.columns) == ['feat_a', 'feat_b']
    assert y.tolist() == [0.1, 0.2, 0.3]


def test_select_matrix_returns_none_label_when_column_absent():
    # Predict-time case: the rows have no label yet.
    df = _frame().drop(columns=['target'])
    X, y = select_matrix(df, ['feat_a', 'feat_b'], 'target')
    assert list(X.columns) == ['feat_a', 'feat_b']
    assert y is None


def test_select_matrix_returns_none_label_when_label_col_is_none():
    df = _frame()
    _, y = select_matrix(df, ['feat_a'], None)
    assert y is None
