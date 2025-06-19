import cloudscraper
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import time
import random
import json
import os
from bs4 import BeautifulSoup
from urllib3.exceptions import ReadTimeoutError
from requests.exceptions import ReadTimeout
import re
import csv
from datetime import datetime

def get_cf_cookies():
    """Получаем cookies через cloudscraper с расширенными настройками"""
    try:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False,
                'desktop': True
            },
            delay=15,
            interpreter='native',
        )
        
        print("Получаем cookies через CloudScraper...")
        resp = scraper.get("https://www.investing.com/news/forex-news", timeout=60)
        
        if resp.status_code == 200:
            print("Успешно получили cookies!")
            return scraper.cookies.get_dict()
        else:
            print(f"Ошибка CloudScraper: HTTP {resp.status_code}")
    except Exception as e:
        print(f"Ошибка в CloudScraper: {str(e)}")
    return None

def save_cookies(cookies, filename="cookies.json"):
    """Сохранение cookies в файл"""
    with open(filename, 'w') as f:
        json.dump(cookies, f)

def load_cookies(filename="cookies.json"):
    """Загрузка cookies из файла"""
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return None

def setup_driver():
    """Настройка undetected-chromedriver с увеличенными таймаутами"""
    options = uc.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument('--disable-popup-blocking')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-web-security')
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    
    # Увеличиваем таймауты
    options.add_argument('--dns-prefetch-disable')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    
    # Добавляем случайный user-agent
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
    ]
    options.add_argument(f'--user-agent={random.choice(user_agents)}')
    
    return uc.Chrome(options=options)

def human_like_scroll(driver):
    """Имитация человеческой прокрутки"""
    total_height = driver.execute_script("return document.body.scrollHeight")
    current_position = 0
    while current_position < total_height:
        scroll_amount = random.randint(100, 300)
        current_position += scroll_amount
        driver.execute_script(f"window.scrollTo(0, {current_position});")
        time.sleep(random.uniform(0.1, 0.3))

def wait_for_cloudflare(driver, timeout=5):
    """Ожидание прохождения Cloudflare проверки"""
    try:
        print("Проверяем наличие Cloudflare...")
        WebDriverWait(driver, timeout).until_not(
            EC.presence_of_element_located((By.ID, "challenge-form"))
        )
        print("Cloudflare проверка пройдена")
        return True
    except TimeoutException:
        print("Cloudflare проверка не обнаружена или не завершена")
        return False

def parse_minutes_ago(text):
    text = text.lower()
    if 'minute' in text:
        return int(re.search(r'(\d+)', text).group(1))
    if 'hour' in text:
        return int(re.search(r'(\d+)', text).group(1)) * 60
    if 'just now' in text:
        return 0
    return 99999  # если не удалось распознать

def get_article_content(driver, timeout=10, max_retries=3):
    """Получение содержимого статьи с улучшенной обработкой ошибок и механизмом повторных попыток"""
    for attempt in range(max_retries):
        try:
            print(f"Попытка {attempt + 1} из {max_retries} получения контента...")
            print("Ожидаем загрузку контента статьи...")
            article_container = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[class*="articlePage"]'))
            )
            print("Основной контейнер статьи найден")
            time.sleep(2)
            html = article_container.get_attribute('innerHTML')
            soup = BeautifulSoup(html, 'html.parser')
            # Фильтруем только <p>, которые не находятся внутри рекламы
            paragraphs = []
            for p in soup.find_all('p'):
                if not p.find_parent(attrs={'data-test': 'contextual-subscription-hook'}):
                    text = p.get_text(strip=True)
                    if text:
                        paragraphs.append(text)
            content = '\n'.join(paragraphs)
            if not content.strip():
                print("Предупреждение: Получен пустой контент")
                if attempt < max_retries - 1:
                    print("Повторяем попытку...")
                    continue
                return None, [], None, None, None
            print(f"Успешно получен контент статьи (длина: {len(content)} символов)")

            # Парсим связанные инструменты (акции/индексы)
            page_html = driver.page_source
            page_soup = BeautifulSoup(page_html, 'html.parser')
            related = []
            related_section = page_soup.find('div', {'data-test': 'related-instruments-section'})
            if related_section:
                for rel in related_section.find_all('div', class_='relative'):
                    a = rel.find('a', href=True)
                    ticker = rel.find('span')
                    if a and ticker:
                        related.append({
                            'url': a['href'],
                            'ticker': ticker.get_text(strip=True)
                        })
            # Парсим автора
            author = None
            author_block = page_soup.find('span', string='Author')
            if author_block:
                author_link = author_block.find_next('a')
                if author_link:
                    author = author_link.get_text(strip=True)
            # Парсим время публикации и апдейта (по следующему <span> после 'Published'/'Updated')
            published = None
            updated = None
            for span in page_soup.find_all('span'):
                if span.get_text(strip=True).lower() == 'published':
                    next_span = span.find_next_sibling('span')
                    while next_span and not next_span.get_text(strip=True):
                        next_span = next_span.find_next_sibling('span')
                    if next_span:
                        published = next_span.get_text(strip=True)
                if span.get_text(strip=True).lower() == 'updated':
                    next_span = span.find_next_sibling('span')
                    while next_span and not next_span.get_text(strip=True):
                        next_span = next_span.find_next_sibling('span')
                    if next_span:
                        updated = next_span.get_text(strip=True)
            return content, related, author, published, updated
        except Exception as e:
            print(f"Ошибка: {e}")
            if attempt < max_retries - 1:
                print("Повторяем попытку...")
                time.sleep(5)
                continue
            return None, [], None, None, None

def get_article_publish_datetime(article):
    try:
        time_elem = article.find_element(By.CSS_SELECTOR, 'time[data-test="article-publish-date"]')
        dt_str = time_elem.get_attribute('datetime')
        return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.min  # если не нашли дату, ставим минимальную

def clean_text(text):
    if not text:
        return ''
    # Удаляем любые последовательности, начинающиеся с 'вЂ' и следующих 1-3 символов (буквы, знаки), в любом регистре
    text = re.sub(r'вЂ.{0,3}', '', text, flags=re.IGNORECASE)
    return (text
        .replace('’', "'")
        .replace('‘', "'")
        .replace('"', '"')
        .replace('"', '"')
        .replace('–', '-')
        .replace('—', '-')
        .replace('…', '...')
        .replace('•', '-')
        .replace('\xa0', ' ')
        .encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
    )

def main():
    # 1. Пробуем загрузить сохраненные cookies
    saved_cookies = load_cookies()
    if saved_cookies:
        print("Загружены сохраненные cookies")
        cf_cookies = saved_cookies
    else:
        # 2. Получаем новые cookies через CloudScraper
        cf_cookies = get_cf_cookies()
        if cf_cookies:
            save_cookies(cf_cookies)
        else:
            print("Не удалось получить cookies. Пробуем без них...")
    
    # 3. Инициализируем драйвер
    driver = setup_driver()
    
    try:
        # 4. Переходим на страницу
        print("Пытаемся загрузить страницу...")
        driver.get("https://www.investing.com/news/forex-news")
        
        # 5. Ждем прохождения Cloudflare
        if not wait_for_cloudflare(driver):
            print("Ожидание прохождения Cloudflare...")
            time.sleep(1)  # Минимальная пауза
        
        # 6. Имитируем человеческое поведение
        human_like_scroll(driver)
        
        # 7. Ждем загрузки контента
        try:
            WebDriverWait(driver, 1).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-test="article-item"]'))
            )
            print("Страница успешно загружена!")
        except:
            raise Exception("Не удалось загрузить контент новостей")
        
        # 8. Собираем статьи и сортируем по времени публикации (от самой свежей)
        articles = driver.find_elements(By.CSS_SELECTOR, 'article[data-test="article-item"]')
        articles_with_time = []
        for article in articles:
            pub_dt = get_article_publish_datetime(article)
            articles_with_time.append((article, pub_dt))
        articles_with_time.sort(key=lambda x: x[1], reverse=True)
        sorted_articles = [a[0] for a in articles_with_time][:5]
        results = []
        
        # Подготовка к CSV
        csv_file = 'articles_latest.csv'
        write_header = not os.path.exists(csv_file)
        csv_fields = ['title', 'link', 'content', 'related', 'author', 'published', 'updated']
        if write_header:
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=csv_fields)
                writer.writeheader()

        for article in sorted_articles:
            try:
                title_element = article.find_element(By.CSS_SELECTOR, 'a[data-test="article-title-link"]')
                title = title_element.text.strip()
                link = title_element.get_attribute('href')
                
                print(f"\nОбрабатываем: {title}")
                print(f"URL статьи: {link}")
                
                # Открываем статью в новой вкладке
                print("Открываем статью в новой вкладке...")
                driver.execute_script("window.open(arguments[0]);", link)
                driver.switch_to.window(driver.window_handles[-1])
                
                try:
                    # Даем странице время на начальную загрузку
                    time.sleep(1)

                    # Проверяем на технические работы
                    if "temporarily down for maintenance" in driver.page_source.lower():
                        print("Сайт временно недоступен (maintenance). Жду 5 минут и пробую следующую статью...")
                        time.sleep(300)
                        continue

                    # Пробуем закрыть или удалить pop-up (оверлей)
                    try:
                        close_svg = driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"] svg')
                        close_svg.click()
                        print("Попап успешно закрыт (svg в dialog).")
                        time.sleep(0.1)
                    except Exception:
                        try:
                            driver.execute_script("""
                                let dialog = document.querySelector('div[role=\"dialog\"]');
                                if(dialog) dialog.remove();
                            """)
                            print("Попап удалён через JS (role=dialog).")
                            time.sleep(0.1)
                        except Exception:
                            print("Не удалось закрыть или удалить попап (role=dialog).")

                    content, related, author, published, updated = get_article_content(driver, timeout=10, max_retries=3)
                    
                    if content:
                        results.append({
                            'title': title,
                            'link': link,
                            'content': content,
                            'related': related,
                            'author': author,
                            'published': published,
                            'updated': updated
                        })
                        print("Статья успешно обработана")
                        # Сохраняем в CSV сразу после обработки
                        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                            writer = csv.DictWriter(f, fieldnames=csv_fields)
                            writer.writerow({
                                'title': clean_text(title),
                                'link': link,
                                'content': clean_text(content),
                                'related': clean_text('; '.join([f'{r["ticker"]} ({r["url"]})' for r in related])),
                                'author': clean_text(author),
                                'published': clean_text(published),
                                'updated': clean_text(updated)
                            })
                    else:
                        print("Не удалось получить контент статьи после всех попыток, переходим к следующей")
                    
                except Exception as e:
                    print(f"Ошибка при обработке статьи: {str(e)}")
                finally:
                    print("Закрываем вкладку со статьей...")
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])
            except Exception as e:
                print(f"Ошибка при обработке статьи: {str(e)}")
                continue
        
        # 9. Выводим результаты
        print("\nУспешно собрано статей:", len(results))
        for idx, article in enumerate(results, 1):
            print(f"\n#{idx}: {article['title']}")
            print(f"Ссылка: {article['link']}")
            print(f"Контент: {article['content']}")
            print("Связанные инструменты:")
            for related in article['related']:
                print(f" - {related['ticker']} ({related['url']})")
            print(f"Автор: {article['author']}")
            print(f"Опубликовано: {article['published']}")
            print(f"Обновлено: {article['updated']}")
            print("-" * 80)
            
    except Exception as e:
        print(f"\nКритическая ошибка: {str(e)}")
        print("Попробуйте:")
        print("1. Запустить скрипт снова")
        print("2. Использовать VPN/прокси")
        print("3. Ввести капчу вручную (если появится)")
        
    finally:
        time.sleep(2)
        driver.quit()

if __name__ == "__main__":
    main()