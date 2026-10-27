from PySide6.QtTest import QTest


def wait_until(pred, timeout=20.0, step=20):
    waited = 0
    while waited < timeout * 1000:
        if pred():
            return True
        QTest.qWait(step)
        waited += step
    return pred()
