import logging
import json
import sys
from datetime import datetime
from app.config import settings

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_logger():
    logger = logging.getLogger("ats")
    logger.setLevel(logging.DEBUG if settings.APP_ENV in ("development", "dev") else logging.INFO)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if settings.APP_ENV in ("development", "dev"):
            handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s", datefmt="%H:%M:%S"))
        else:
            handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger

logger = setup_logger()
