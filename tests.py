from app import app

def test_homepage():
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200
    # assert b'Early Registration Ends August 18, 2024' in response.data  # Replace with actual content to test
