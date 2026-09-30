import unittest
from unittest.mock import MagicMock, patch

from lazy_termin import scraper


class BrowserHelperTests(unittest.TestCase):
	def test_click_element_falls_back_to_javascript_after_intercepted_click(self):
		driver = MagicMock()
		element = MagicMock()
		from selenium.common.exceptions import ElementClickInterceptedException

		element.click.side_effect = ElementClickInterceptedException()

		scraper.click_element(driver, element)

		driver.execute_script.assert_called_once()
		self.assertIs(driver.execute_script.call_args.args[1], element)

	def test_driver_quits_when_flow_returns_early(self):
		driver = MagicMock()
		wait = MagicMock()
		wait.until.side_effect = [MagicMock(), []]  # No "Verlängerung" button

		with patch.object(scraper, "setup_driver", return_value=driver), \
			patch.object(scraper, "WebDriverWait", return_value=wait), \
			patch.object(scraper, "get_random_wait_time"):
			scraper.main()

		driver.quit.assert_called_once_with()

	def test_driver_quits_when_flow_raises(self):
		driver = MagicMock()
		driver.get.side_effect = RuntimeError("page down")

		with patch.object(scraper, "setup_driver", return_value=driver), \
			self.assertRaises(RuntimeError):
			scraper.main()

		driver.quit.assert_called_once_with()


if __name__ == "__main__":
	unittest.main()
