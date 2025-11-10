from app import app, socketio
import os

# For Gunicorn
application = app

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5005))
    socketio.run(app, host='0.0.0.0', port=port)