import re
from datetime import datetime

def parse_ocr_metadata(ocr_text):
    result = {
        "temperature_f": None,
        "capture_date": None,
        "capture_time": None,
        "capture_datetime": None,
    }

    for text in ocr_text:
        
        # temperature
        temp_match = re.search(r"(\d+)F", text)

        if temp_match:
            result["temperature_f"] = float(
                temp_match.group(1)
            )

        # date
        date_match = re.search(
            r"(\d{2}-\d{2}-\d{4})",
            text
        )

        if date_match:
            try:
                result["capture_date"] = datetime.strptime(
                    date_match.group(1),
                    "%m-%d-%Y"      
                )
            except:
                pass

        # time
        time_match = re.search(
            r"(\d{2}:\d{2}:\d{2})",
            text
        )

        if time_match:
            try:
                result["capture_time"] = datetime.strptime(
                    time_match.group(1),
                    "%H:%M:%S"
                ).time()
            except:
                pass

    
    if (
        result["capture_date"] and
        result["capture_time"]
    ):
        result["capture_datetime"] = datetime.combine(
            result["capture_date"],
            result["capture_time"]
        )

    return result