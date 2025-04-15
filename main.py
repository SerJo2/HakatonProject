from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from openai import OpenAI
import requests
import logging
import time


from prefs import API_KEY, BASE_URL
from input import QUESTION_TEST, URL_TEST

#logging.basicConfig(level=logging.INFO, filename="py_log.log",filemode="w")

# TODO обработка файлов, обработка текста с картинок, добавить прогркссбар

class WebScraper:
    """Класс для парсинга сайтов"""

    def __init__(self):
        self.visited_urls = set()
        self.content = []
        self.base_domain = ""
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36'})

    @staticmethod
    def _is_valid_url(url):
        """Проверка валидности url"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False

    def _is_same_domain(self, url):
        """Проверка того, что внешняя ссылка имеет тот же домен"""
        target_domain = urlparse(url).netloc
        return target_domain == self.base_domain

    @staticmethod
    def _extract_content(soup):
        """Превращает html код в обычный текст"""
        content = [soup.get_text(separator=' ', strip=True)]


        for table in soup.find_all('table'):
            content.append(table.get_text(separator=' | ', strip=True))


        for lst in soup.find_all(['ul', 'ol']):
            items = [li.get_text(strip=True) for li in lst.find_all('li')]
            content.append(' '.join(items))

        return ' '.join(content)

    def scrape_page(self, url):
        """Парсит страницу"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            logging.info(url, self._extract_content(soup))
            return self._extract_content(soup)
        except Exception as e:
            logging.error(f"Error scraping {url}: {str(e)}")
            return ""

    def get_links(self, url):
        """Получает ссылки со страницы"""
        try:
            response = self.session.get(url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            links = set()

            for link in soup.find_all('a', href=True):
                absolute_url = urljoin(url, link['href'])
                if self._is_valid_url(absolute_url) and self._is_same_domain(absolute_url):
                    links.add(absolute_url)

            return list(links)
        except Exception as e:
            logging.error("Error getting links from {url}: {str(e)}")
            return []

    def scrape_site(self, base_url):
        """Парсинг всего сайта с внешними ссылками"""
        if not self._is_valid_url(base_url):
            raise ValueError("Invalid URL provided")

        self.base_domain = urlparse(base_url).netloc
        self.visited_urls.clear()
        self.content = []

        # Scrape base URL (depth 0)
        self.content.append(self.scrape_page(base_url))
        self.visited_urls.add(base_url)

        # Scrape linked pages (depth 1)
        for link in self.get_links(base_url):
            if link not in self.visited_urls:
                self.content.append(self.scrape_page(link))
                self.visited_urls.add(link)

        return ' '.join(self.content).strip()

class LlamaApi:
    """Класс для LLM"""
    def __init__(self, api_key, base_url):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self.model = "llama-3.3-70b-instruct"

    def compress_text(self, text):
        """Сжатие информации с помощью LLM"""

        logging.info("начало Сжатия")
        try:
            response = self.client.chat.completions.create(
                model="gemini-2.0-flash-lite-001",
                messages=[
                    {"role": "user", "content": "Сократи данный текст без потерь важной информации(Сохрани всю информацию "
                                                "об организаторах, месте и дат проведения, контактами, структуре мероприятия, формат проведения, "
                                                "стоимости участия, соцсетях, призах, условиях участия, дат принятия заявок/даты этапов,"
                                                "кто будет учавствовать и тд"
                                                "): " + text}
                ],
                max_tokens=20000,
                temperature=0.1
            )
            logging.info("Использовано токенов: " + str(response.usage.total_tokens))
            (response.choices[0].message.content.strip())
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.critical(f"API Error: {str(e)}")
            return "Информация не найдена на странице."

    def generate_answer(self, context, question):
        """Генерация ответа, принимает контекст и вопрос"""
        prompt = f"""Тебе даются данные с сайта. Далее тебе будут заданы вопросы по данным с этого сайта. 
        Ты должен ответить на данные вопросы или, если информация не найдена ответить "Информация не найдена на странице.".

        Content: {context}"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": question}
                ],
                max_tokens=50000,
                temperature=0.7
            )
            logging.info("Кол-во токенов: " + str(response.usage.total_tokens))
            return response.choices[0].message.content.strip()
        except Exception as e:
            logging.critical("API Error: {str(e)}")
            return "Информация не найдена на странице."

class ChatBot:
    """Класс для реализации консольного бота"""
    def __init__(self, api_key, base_url):
        self.scraper = WebScraper()
        self.api = LlamaApi(api_key, base_url)
        self.context = ""

    def load_website(self, url):
        """Загрузка вебсайта и парсинг его текста и текста с внутренних ссылок"""
        try:
            self.context = self._compress_context(self.scraper.scrape_site(url))
            return "Данные успешно загружены. Задавайте вопросы."
        except Exception as e:
            return f"Ошибка: {str(e)}"

    def _compress_context(self, text):
        return self.api.compress_text(text)


    def ask_question(self, question):
        """Задание вопроса LLM"""
        if not self.context:
            return "Сначала загрузите данные сайта."

        return self.api.generate_answer(self.context, question)

def main():







    start_time = time.time()
    print("Происходит запуск бота...")
    end_time = time.time()
    bot = ChatBot(API_KEY, BASE_URL)
    elapsed_time = end_time - start_time
    print(f"Бот запущен за {elapsed_time:.2f} секунд")


    for site in URL_TEST:
        start_time = time.time()
        print("Происходит анализ сайта " + site + "...")
        result = bot.load_website(site)
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"Анализ сайта завершен за {elapsed_time:.2f} секунд")

        logging.info(bot.context)
        logging.info("\nБот готов к вопросам")

        for i in QUESTION_TEST:
            question = i
            print(f"Вопрос: {i}.")
            start_time = time.time()
            print(f"Ответ: {bot.ask_question(question)}", end=" ")
            end_time = time.time()
            elapsed_time = end_time - start_time
            print(f"Ответ занял {elapsed_time:.2f} секунд\n")
if __name__ == "__main__":
    main()