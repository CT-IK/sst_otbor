"""
Сервис для работы с Google Sheets API.
Экспорт данных анкет в Google таблицы.
"""
import re
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False
    gspread = None
    Credentials = None

logger = logging.getLogger(__name__)


class GoogleSheetsService:
    """Сервис для работы с Google Sheets"""
    
    # Имя листа для отслеживания выгруженных пользователей
    TRACKING_SHEET_NAME = "Выгруженные"
    
    def __init__(self, credentials_path: str = "credentials.json"):
        """
        Инициализация сервиса.
        
        Args:
            credentials_path: Путь к файлу с credentials сервисного аккаунта Google
        """
        self.credentials_path = Path(credentials_path)
        self._client: Optional[gspread.Client] = None
    
    def _get_client(self) -> gspread.Client:
        """Получить клиент Google Sheets (создаёт при первом обращении)"""
        if not GOOGLE_SHEETS_AVAILABLE:
            raise RuntimeError(
                "Библиотеки gspread и google-auth не установлены. "
                "Установите их: pip install gspread google-auth google-auth-oauthlib google-auth-httplib2"
            )
        
        if self._client is None:
            if not self.credentials_path.exists():
                raise FileNotFoundError(
                    f"Файл credentials.json не найден по пути: {self.credentials_path.absolute()}"
                )
            
            # Загружаем credentials
            creds = Credentials.from_service_account_file(
                str(self.credentials_path),
                scopes=[
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive'
                ]
            )
            
            self._client = gspread.authorize(creds)
            logger.info("Google Sheets клиент инициализирован")
        
        return self._client
    
    def _extract_spreadsheet_id(self, url: str) -> str:
        """
        Извлечь ID таблицы из URL.
        
        Args:
            url: URL Google таблицы (например, https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit)
        
        Returns:
            ID таблицы
        """
        # Паттерны для разных форматов URL
        patterns = [
            r'/spreadsheets/d/([a-zA-Z0-9-_]+)',
            r'id=([a-zA-Z0-9-_]+)',
            r'([a-zA-Z0-9-_]{44})',  # Прямой ID (44 символа)
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        raise ValueError(f"Не удалось извлечь ID таблицы из URL: {url}")
    
    def _get_or_create_tracking_sheet(self, spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
        """
        Получить или создать лист для отслеживания выгруженных пользователей.
        
        Args:
            spreadsheet: Объект таблицы
        
        Returns:
            Лист для отслеживания
        """
        try:
            worksheet = spreadsheet.worksheet(self.TRACKING_SHEET_NAME)
            logger.info(f"Лист '{self.TRACKING_SHEET_NAME}' найден")
        except gspread.WorksheetNotFound:
            # Создаём новый лист
            worksheet = spreadsheet.add_worksheet(
                title=self.TRACKING_SHEET_NAME,
                rows=1000,
                cols=10
            )
            # Устанавливаем заголовки
            worksheet.append_row([
                "ID пользователя",
                "Telegram ID",
                "Имя",
                "Фамилия",
                "Дата выгрузки"
            ])
            logger.info(f"Создан лист '{self.TRACKING_SHEET_NAME}'")
        
        return worksheet
    
    def _get_exported_user_ids(self, tracking_sheet: gspread.Worksheet) -> set[int]:
        """
        Получить множество ID пользователей, которые уже выгружены.
        
        Args:
            tracking_sheet: Лист для отслеживания
        
        Returns:
            Множество ID пользователей
        """
        try:
            # Читаем все значения (начиная со второй строки, первая - заголовки)
            values = tracking_sheet.get_all_values()
            if len(values) <= 1:
                return set()
            
            # Первая колонка - ID пользователя
            user_ids = set()
            for row in values[1:]:  # Пропускаем заголовок
                if row and row[0].strip():
                    try:
                        user_id = int(row[0].strip())
                        user_ids.add(user_id)
                    except ValueError:
                        continue
            
            logger.info(f"Найдено {len(user_ids)} уже выгруженных пользователей")
            return user_ids
        except Exception as e:
            logger.error(f"Ошибка при чтении листа отслеживания: {e}")
            return set()
    
    def _prepare_questionnaire_data(
        self,
        questionnaire: Dict[str, Any],
        questions: List[Dict[str, Any]]
    ) -> List[Any]:
        """
        Подготовить данные анкеты для экспорта в строку таблицы.
        
        Args:
            questionnaire: Данные анкеты
            questions: Список вопросов (для правильного порядка колонок)
        
        Returns:
            Список значений для строки
        """
        # Создаём map вопросов для быстрого доступа
        question_map = {q['id']: q for q in questions}
        
        # Начинаем с базовой информации
        row = [
            questionnaire.get('user_id'),
            questionnaire.get('telegram_id'),
            questionnaire.get('user_name', ''),
            questionnaire.get('submitted_at', '').strftime('%d.%m.%Y %H:%M') if questionnaire.get('submitted_at') else '',
        ]
        
        # Добавляем ответы на вопросы в порядке вопросов
        answers = questionnaire.get('answers', {})
        for question in questions:
            qid = str(question['id'])
            answer_value = answers.get(qid, '')
            
            # Форматируем ответ
            if isinstance(answer_value, list):
                answer = ', '.join(str(v) for v in answer_value)
            elif isinstance(answer_value, dict):
                answer = str(answer_value)
            else:
                answer = str(answer_value) if answer_value else ''
            
            row.append(answer)
        
        return row
    
    def export_questionnaires(
        self,
        sheet_url: str,
        questionnaires: List[Dict[str, Any]],
        questions: List[Dict[str, Any]],
        faculty_name: str
    ) -> Dict[str, Any]:
        """
        Экспортировать анкеты в Google таблицу.
        
        Args:
            sheet_url: URL Google таблицы
            questionnaires: Список анкет для экспорта
            questions: Список вопросов (для заголовков и порядка)
            faculty_name: Название факультета
        
        Returns:
            Словарь с результатами:
            {
                'success': bool,
                'exported_count': int,
                'skipped_count': int,
                'total_in_sheet': int,
                'error': str | None
            }
        """
        try:
            client = self._get_client()
            spreadsheet_id = self._extract_spreadsheet_id(sheet_url)
            spreadsheet = client.open_by_key(spreadsheet_id)
            
            # Получаем или создаём основной лист
            try:
                main_sheet = spreadsheet.sheet1  # Первый лист
            except Exception:
                main_sheet = spreadsheet.add_worksheet(title="Анкеты", rows=1000, cols=20)
            
            # Получаем или создаём лист отслеживания
            tracking_sheet = self._get_or_create_tracking_sheet(spreadsheet)
            
            # Получаем уже выгруженных пользователей
            exported_ids = self._get_exported_user_ids(tracking_sheet)
            
            # Подготавливаем заголовки
            headers = [
                "ID пользователя",
                "Telegram ID",
                "Имя",
                "Дата отправки"
            ]
            headers.extend([q.get('text', f"Вопрос {q['id']}")[:50] for q in questions])
            
            # Проверяем, есть ли уже заголовки
            existing_headers = main_sheet.row_values(1) if main_sheet.row_values(1) else []
            if not existing_headers or existing_headers != headers:
                # Обновляем заголовки
                main_sheet.clear()
                main_sheet.append_row(headers)
                logger.info("Заголовки таблицы обновлены")
            
            # Экспортируем анкеты
            exported_count = 0
            skipped_count = 0
            
            for questionnaire in questionnaires:
                user_id = questionnaire.get('user_id')
                
                # Пропускаем уже выгруженных
                if user_id in exported_ids:
                    skipped_count += 1
                    continue
                
                # Подготавливаем данные
                row_data = self._prepare_questionnaire_data(questionnaire, questions)
                
                # Добавляем строку в основную таблицу
                main_sheet.append_row(row_data)
                
                # Добавляем запись в лист отслеживания
                from datetime import datetime
                tracking_sheet.append_row([
                    user_id,
                    questionnaire.get('telegram_id', ''),
                    questionnaire.get('user_name', '').split()[0] if questionnaire.get('user_name') else '',
                    questionnaire.get('user_name', '').split()[-1] if questionnaire.get('user_name') else '',
                    datetime.now().strftime('%d.%m.%Y %H:%M')
                ])
                
                exported_count += 1
                exported_ids.add(user_id)  # Добавляем в кэш
            
            # Подсчитываем общее количество в таблице
            total_in_sheet = len(main_sheet.get_all_values()) - 1  # Минус заголовок
            
            logger.info(
                f"Экспорт завершён: выгружено {exported_count}, пропущено {skipped_count}, "
                f"всего в таблице {total_in_sheet}"
            )
            
            return {
                'success': True,
                'exported_count': exported_count,
                'skipped_count': skipped_count,
                'total_in_sheet': total_in_sheet,
                'error': None
            }
            
        except FileNotFoundError as e:
            error_msg = f"Файл credentials.json не найден: {e}"
            logger.error(error_msg)
            return {
                'success': False,
                'exported_count': 0,
                'skipped_count': 0,
                'total_in_sheet': 0,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Ошибка при экспорте в Google Sheets: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                'success': False,
                'exported_count': 0,
                'skipped_count': 0,
                'total_in_sheet': 0,
                'error': error_msg
            }
    
    def get_exported_count(self, sheet_url: str) -> int:
        """
        Получить количество выгруженных анкет из Google таблицы.
        
        Args:
            sheet_url: URL Google таблицы
        
        Returns:
            Количество выгруженных анкет (количество строк минус заголовок)
        """
        if not GOOGLE_SHEETS_AVAILABLE:
            logger.warning("Google Sheets библиотеки не установлены, возвращаю 0")
            return 0
        
        try:
            client = self._get_client()
            spreadsheet_id = self._extract_spreadsheet_id(sheet_url)
            spreadsheet = client.open_by_key(spreadsheet_id)
            
            # Получаем основной лист
            main_sheet = spreadsheet.sheet1
            all_values = main_sheet.get_all_values()
            
            # Количество строк минус заголовок
            count = len(all_values) - 1 if len(all_values) > 1 else 0
            return max(0, count)
            
        except Exception as e:
            logger.error(f"Ошибка при получении количества выгруженных: {e}")
            return 0


# Singleton
google_sheets_service = GoogleSheetsService()
