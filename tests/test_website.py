import os
import sys

base_path = os.path.dirname(os.path.realpath(__file__))
app_path = os.path.dirname(base_path)
sys.path.append(app_path)
from app import app

class TestHomepage:
    client = app.test_client()
    response = client.get('/')

    def test_response_code(self):
        assert self.response.status_code == 200

    def test_early_reg(self):
        html_line = f'<h2>Early Registration Ends <font color="red">{os.environ.get("EARLY_REG_DATE")}</font></h2>'
        assert html_line.encode() in self.response.data
    
    def test_reg_close(self):
        html_line = f'<h2>Registration Closes <font color="red">{os.environ.get("REG_CLOSE_DATE")}</font></h2>'
        assert html_line.encode() in self.response.data

    def test_contact_email(self):
        html_line = f'You can contact us at <a href="mailto:{os.environ.get("CONTACT_EMAIL")}">{os.environ.get("CONTACT_EMAIL")}</a> if you have questions or issues.'
        assert html_line.encode() in self.response.data

if __name__ == "__main__":
    homepage = TestHomepage()
    print(homepage.test_response_code())