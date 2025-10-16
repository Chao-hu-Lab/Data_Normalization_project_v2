import tkinter as tk
from tkinter import messagebox, ttk, scrolledtext, filedialog
import importlib.util
import os
import sys
import traceback
import threading
import queue
import logging
from datetime import datetime
import subprocess
import psutil
import re

class DataNormalizationApp:
    def __init__(self, master):
        self.master = master
        master.title("Data Normalization Workflow v2")
        master.geometry("1200x850")
        
        # 🎨 優化色彩方案
        self.color_scheme = {
            'background': '#f4f6f9',
            'panel_bg': '#ffffff',
            'primary': '#3498db',
            'success': '#2ecc71',
            'warning': '#f39c12',
            'danger': '#e74c3c',
            'text_dark': '#2c3e50',
            'text_light': '#7f8c8d',
            'running': '#e67e22',
            'border': '#e0e0e0'
        }
        
        master.configure(bg=self.color_scheme['background'])

        # 執行狀態管理
        self.completed_steps = set()
        self.current_thread = None
        self.cancel_flag = threading.Event()
        self.progress_queue = queue.Queue()
        self.is_executing = False
        self.log_queue = queue.Queue()
        
        # 檔案選擇相關
        self.file_selected = threading.Event()
        self.selected_file_path = None
        
        # 統計資訊
        self.current_stats = {
            'step_name': '',
            'file_path': '',
            'metabolites': 0,
            'samples': 0,
            'output_path': ''
        }
        
        # 🔧 新增：用於從終端機輸出抓取資訊
        self.output_buffer = []
        
        # 設置樣式
        self.style = ttk.Style()
        self.style.theme_use('clam')
        self.configure_styles()
        
        # 創建主框架
        self.create_main_layout()
        
        # 創建標題和控制按鈕
        self.create_header()
        
        # 創建左右分欄
        self.create_split_layout()
        
        # 左側：步驟區域
        self.create_steps_area()
        
        # 右側：統計面板
        self.create_stats_panel()
        
        # 底部：結果預覽區域
        self.create_result_preview_area()
        
        # 設置日誌系統
        self.setup_logging()
        
        # 開始檢查進度和日誌
        self.check_progress()
        self.check_log_queue()
        self.update_stats_display()
        
        # 初始化按鈕狀態
        self.update_button_states()

    def setup_logging(self):
        """設置日誌系統"""
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(
            log_dir, 
            f'normalization_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        )
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        gui_handler = QueueHandler(self.log_queue)
        gui_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(gui_handler)
        
        self.logger.info("=" * 80)
        self.logger.info("Data Normalization Workflow v2 啟動")
        self.logger.info("=" * 80)

    def configure_styles(self):
        """🎨 配置統一的樣式 - 使用微軟正黑體和Times New Roman"""
        # 主框架
        self.style.configure('Main.TFrame', background=self.color_scheme['background'])
        
        # 步驟框架
        self.style.configure('Step.TFrame', 
                             background=self.color_scheme['panel_bg'], 
                             relief='flat',
                             borderwidth=0)
        
        # 統計面板框架
        self.style.configure('Stats.TFrame',
                             background=self.color_scheme['panel_bg'],
                             relief='flat',
                             borderwidth=0)
        
        # 標題標籤 - 中文使用微軟正黑體
        self.style.configure('Title.TLabel', 
                             font=('Microsoft JhengHei', 18, 'bold'), 
                             foreground=self.color_scheme['text_dark'], 
                             background=self.color_scheme['background'])
        
        # 提示標籤 - 中文使用微軟正黑體
        self.style.configure('Notice.TLabel', 
                             font=('Microsoft JhengHei', 9), 
                             foreground=self.color_scheme['text_light'], 
                             background=self.color_scheme['background'])
        
        # 步驟按鈕
        self.style.configure('Step.TButton', 
                             font=('Microsoft JhengHei', 10, 'bold'),
                             borderwidth=0,
                             relief='flat')
        
        # 統計標籤 - 無底色
        self.style.configure('Stats.TLabel',
                             font=('Microsoft JhengHei', 9),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])
        
        # 統計標題標籤
        self.style.configure('StatsTitle.TLabel',
                             font=('Microsoft JhengHei', 9, 'bold'),
                             background=self.color_scheme['panel_bg'],
                             foreground=self.color_scheme['text_dark'])

    def create_main_layout(self):
        """創建主佈局"""
        self.main_frame = ttk.Frame(self.master, style='Main.TFrame')
        self.main_frame.pack(padx=20, pady=20, fill=tk.BOTH, expand=True)

    def create_header(self):
        """創建標題和控制按鈕"""
        header_frame = ttk.Frame(self.main_frame, style='Main.TFrame')
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 左側：標題
        title_frame = ttk.Frame(header_frame, style='Main.TFrame')
        title_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.title_label = ttk.Label(
            title_frame, 
            text="Data Normalization Workflow v2", 
            style='Title.TLabel'
        )
        self.title_label.pack(anchor='w')
        
        notice_text = (
            "📋 請確保資料已過VBA統一格式 | 四個腳本必須與GUI程式在同一目錄 | "
            "依序執行：ISTD→QC→批次→濃度"
        )
        
        self.notice_label = ttk.Label(
            title_frame, 
            text=notice_text,
            style='Notice.TLabel'
        )
        self.notice_label.pack(anchor='w', pady=(5, 0))
        
        # 右側：控制按鈕
        control_frame = ttk.Frame(header_frame, style='Main.TFrame')
        control_frame.pack(side=tk.RIGHT, padx=(10, 0))
        
        button_width = 12
        
        self.cancel_btn = ttk.Button(
            control_frame,
            text="⏹ 取消執行",
            command=self.cancel_execution,
            state='disabled',
            width=button_width
        )
        self.cancel_btn.pack(pady=2, fill=tk.X)
        
        self.reset_btn = ttk.Button(
            control_frame,
            text="🔄 重置步驟",
            command=self.reset_all_steps,
            width=button_width
        )
        self.reset_btn.pack(pady=2, fill=tk.X)
        
        self.clear_log_btn = ttk.Button(
            control_frame,
            text="🗑 清除日誌",
            command=self.clear_log,
            width=button_width
        )
        self.clear_log_btn.pack(pady=2, fill=tk.X)

    def create_split_layout(self):
        """創建左右分欄佈局"""
        self.split_frame = ttk.Frame(self.main_frame, style='Main.TFrame')
        self.split_frame.pack(fill=tk.BOTH, expand=False, pady=10)
        
        # 左側框架（步驟區域）
        self.left_frame = ttk.Frame(self.split_frame, style='Main.TFrame')
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # 右側框架（統計面板）
        self.right_frame = ttk.Frame(self.split_frame, style='Main.TFrame')
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False)

    def create_steps_area(self):
        """創建步驟區域"""
        steps_container = ttk.LabelFrame(
            self.left_frame, 
            text="處理步驟", 
            padding=10
        )
        steps_container.pack(fill=tk.BOTH, expand=True)

        self.steps = [
            {
                "name": "ISTD校正", 
                "script": "ISTD_Correction_v2", 
                "color": "#3498db",
                "dependencies": []
            },
            {
                "name": "QC校正", 
                "script": "QC_LOWESS_v2", 
                "color": "#2ecc71",
                "dependencies": ["ISTD校正"]
            },
            {
                "name": "批次校正", 
                "script": "Batch_Effect_v2", 
                "color": "#e74c3c",
                "dependencies": ["ISTD校正", "QC校正"]
            },
            {
                "name": "濃度校正", 
                "script": "Concentration_Normalization_v2", 
                "color": "#f39c12",
                "dependencies": ["ISTD校正", "QC校正", "批次校正"]
            }
        ]

        self.step_buttons = []
        self.step_status_labels = []
        self.step_frames = []

        for step in self.steps:
            step_frame = self.create_step_frame(steps_container, step)
            step_frame.pack(fill=tk.X, pady=5, padx=5)
            self.step_frames.append(step_frame)

    def create_step_frame(self, parent, step):
        """創建單個步驟框架"""
        # 🎨 使用Frame替代ttk.Frame以獲得更好的邊框控制
        step_frame = tk.Frame(
            parent, 
            bg=self.color_scheme['panel_bg'],
            highlightbackground=self.color_scheme['border'],
            highlightthickness=1,
            relief='flat'
        )

        step_label = tk.Label(
            step_frame, 
            text=step['name'], 
            width=12,
            font=('Microsoft JhengHei', 11, 'bold'),
            foreground=step['color'],
            bg=self.color_scheme['panel_bg']
        )
        step_label.pack(side=tk.LEFT, padx=10, pady=5)

        if step['dependencies']:
            dep_text = f"(需先完成: {', '.join(step['dependencies'])})"
            dep_label = tk.Label(
                step_frame,
                text=dep_text,
                font=('Microsoft JhengHei', 8),
                foreground='gray',
                bg=self.color_scheme['panel_bg']
            )
            dep_label.pack(side=tk.LEFT, padx=5)

        execute_btn = ttk.Button(
            step_frame, 
            text="▶ 執行", 
            width=10,
            style='Step.TButton',
            command=lambda s=step: self.execute_step(s)
        )
        execute_btn.pack(side=tk.RIGHT, padx=10, pady=5)

        status_label = tk.Label(
            step_frame, 
            text="⚪ 未執行", 
            foreground="gray", 
            font=('Microsoft JhengHei', 10),
            bg=self.color_scheme['panel_bg']
        )
        status_label.pack(side=tk.RIGHT, padx=10)

        self.step_buttons.append(execute_btn)
        self.step_status_labels.append(status_label)

        return step_frame

    def create_stats_panel(self):
        """🎨 創建統計面板 - 優化樣式"""
        # 使用tk.Frame替代ttk.LabelFrame以獲得更好的樣式控制
        stats_outer = tk.Frame(
            self.right_frame,
            bg=self.color_scheme['panel_bg'],
            highlightbackground=self.color_scheme['border'],
            highlightthickness=1,
            relief='flat'
        )
        stats_outer.pack(fill=tk.BOTH, expand=True)
        stats_outer.pack_propagate(False)
        stats_outer.config(width=280)
        
        # 標題
        title_label = tk.Label(
            stats_outer,
            text="📊 處理統計",
            font=('Microsoft JhengHei', 12, 'bold'),
            bg=self.color_scheme['panel_bg'],
            fg=self.color_scheme['text_dark']
        )
        title_label.pack(anchor='w', padx=15, pady=(15, 10))
        
        # 內容容器
        stats_container = tk.Frame(stats_outer, bg=self.color_scheme['panel_bg'])
        stats_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 15))
        
        # 當前步驟
        tk.Label(
            stats_container,
            text="當前步驟：",
            font=('Microsoft JhengHei', 9, 'bold'),
            bg=self.color_scheme['panel_bg'],
            fg=self.color_scheme['text_dark']
        ).pack(anchor='w', pady=(0, 2))
        
        self.stats_step_label = tk.Label(
            stats_container,
            text="等待執行...",
            font=('Microsoft JhengHei', 10),
            foreground=self.color_scheme['primary'],
            bg=self.color_scheme['panel_bg']
        )
        self.stats_step_label.pack(anchor='w', pady=(0, 15))
        
        # 處理檔案
        tk.Label(
            stats_container,
            text="處理檔案：",
            font=('Microsoft JhengHei', 9, 'bold'),
            bg=self.color_scheme['panel_bg'],
            fg=self.color_scheme['text_dark']
        ).pack(anchor='w', pady=(0, 2))
        
        self.stats_file_label = tk.Label(
            stats_container,
            text="未選擇",
            font=('Microsoft JhengHei', 9),
            foreground=self.color_scheme['text_dark'],
            bg=self.color_scheme['panel_bg'],
            wraplength=240,
            justify='left'
        )
        self.stats_file_label.pack(anchor='w', pady=(0, 15))
        
        # 數據統計
        tk.Label(
            stats_container,
            text="數據統計：",
            font=('Microsoft JhengHei', 9, 'bold'),
            bg=self.color_scheme['panel_bg'],
            fg=self.color_scheme['text_dark']
        ).pack(anchor='w', pady=(0, 2))
        
        self.stats_data_label = tk.Label(
            stats_container,
            text="代謝物：- | 樣本：-",
            font=('Times New Roman', 9),
            foreground=self.color_scheme['text_dark'],
            bg=self.color_scheme['panel_bg']
        )
        self.stats_data_label.pack(anchor='w', pady=(0, 15))
        
        # 輸出路徑
        tk.Label(
            stats_container,
            text="輸出路徑：",
            font=('Microsoft JhengHei', 9, 'bold'),
            bg=self.color_scheme['panel_bg'],
            fg=self.color_scheme['text_dark']
        ).pack(anchor='w', pady=(0, 2))
        
        output_frame = tk.Frame(stats_container, bg=self.color_scheme['panel_bg'])
        output_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.stats_output_label = tk.Label(
            output_frame,
            text="未生成",
            font=('Microsoft JhengHei', 9),
            foreground=self.color_scheme['text_dark'],
            bg=self.color_scheme['panel_bg'],
            wraplength=180,
            justify='left'
        )
        self.stats_output_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.open_folder_btn = ttk.Button(
            output_frame,
            text="📂",
            width=3,
            command=self.open_output_folder,
            state='disabled'
        )
        self.open_folder_btn.pack(side=tk.RIGHT)
        
        # 系統資源
        tk.Label(
            stats_container,
            text="系統資源：",
            font=('Microsoft JhengHei', 9, 'bold'),
            bg=self.color_scheme['panel_bg'],
            fg=self.color_scheme['text_dark']
        ).pack(anchor='w', pady=(10, 2))
        
        self.stats_resource_label = tk.Label(
            stats_container,
            text="CPU: -% | 記憶體: - MB",
            font=('Times New Roman', 9),
            foreground=self.color_scheme['text_dark'],
            bg=self.color_scheme['panel_bg']
        )
        self.stats_resource_label.pack(anchor='w')

    def create_result_preview_area(self):
        """創建結果預覽區域"""
        preview_container = ttk.LabelFrame(
            self.main_frame, 
            text="執行日誌（實時顯示）", 
            padding=10
        )
        preview_container.pack(fill=tk.BOTH, expand=True, pady=10)

        self.result_text = scrolledtext.ScrolledText(
            preview_container, 
            height=15, 
            wrap=tk.WORD,
            font=('Consolas', 9),
            bg='#1e1e1e',
            fg='#d4d4d4'
        )
        self.result_text.pack(fill=tk.BOTH, expand=True)
        
        # 🎨 日誌標籤 - 無底色
        self.result_text.tag_config('INFO', foreground='#4ec9b0')
        self.result_text.tag_config('SUCCESS', foreground='#4ec9b0', font=('Consolas', 9, 'bold'))
        self.result_text.tag_config('ERROR', foreground='#f48771', font=('Consolas', 9, 'bold'))
        self.result_text.tag_config('WARNING', foreground='#dcdcaa')
        self.result_text.tag_config('DEBUG', foreground='#808080')
        self.result_text.tag_config('CRITICAL', foreground='#ff0000', font=('Consolas', 9, 'bold'))

    def update_stats_display(self):
        """更新統計顯示"""
        # 更新系統資源
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_info = psutil.Process().memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            self.stats_resource_label.config(
                text=f"CPU: {cpu_percent:.1f}% | Memory: {memory_mb:.1f} MB"
            )
        except:
            pass
        
        # 每秒更新一次
        self.master.after(1000, self.update_stats_display)

    def open_output_folder(self):
        """開啟輸出資料夾"""
        if self.current_stats['output_path'] and os.path.exists(self.current_stats['output_path']):
            folder_path = os.path.dirname(self.current_stats['output_path'])
            if sys.platform == 'win32':
                # Windows: 使用 explorer /select 選中檔案
                os.system(f'explorer /select,"{os.path.abspath(self.current_stats["output_path"])}"')
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', self.current_stats['output_path']])
            else:
                subprocess.Popen(['xdg-open', folder_path])
        else:
            messagebox.showwarning("提示", "輸出路徑不存在或尚未生成")

    def check_progress(self):
        """定期檢查進度隊列"""
        try:
            while True:
                progress_data = self.progress_queue.get_nowait()
                
                if isinstance(progress_data, dict):
                    # 更新統計資訊
                    if 'file_path' in progress_data:
                        self.current_stats['file_path'] = progress_data['file_path']
                        filename = os.path.basename(progress_data['file_path'])
                        self.stats_file_label.config(text=filename)
                    
                    if 'metabolites' in progress_data:
                        self.current_stats['metabolites'] = progress_data['metabolites']
                        self.stats_data_label.config(
                            text=f"Metabolites: {self.current_stats['metabolites']} | Samples: {self.current_stats['samples']}"
                        )
                    
                    if 'samples' in progress_data:
                        self.current_stats['samples'] = progress_data['samples']
                        self.stats_data_label.config(
                            text=f"Metabolites: {self.current_stats['metabolites']} | Samples: {self.current_stats['samples']}"
                        )
                    
                    if 'output_path' in progress_data:
                        self.current_stats['output_path'] = progress_data['output_path']
                        filename = os.path.basename(progress_data['output_path'])
                        self.stats_output_label.config(text=filename)
                        self.open_folder_btn.config(state='normal')
                
                self.master.update_idletasks()
        except queue.Empty:
            pass
        
        self.master.after(100, self.check_progress)

    def check_log_queue(self):
        """定期檢查日誌隊列"""
        try:
            while True:
                log_record = self.log_queue.get_nowait()
                self.display_log(log_record)
                
                # 🔧 從日誌中提取統計資訊
                self.parse_log_for_stats(log_record)
                
        except queue.Empty:
            pass
        
        self.master.after(50, self.check_log_queue)

    def parse_log_for_stats(self, log_record):
        """🔧 從日誌記錄中解析統計資訊"""
        message = log_record.getMessage()
        
        # 提取代謝物數量
        metabolite_match = re.search(r'代謝物[數数量]*[:：\s]*(\d+)', message)
        if metabolite_match:
            metabolites = int(metabolite_match.group(1))
            self.current_stats['metabolites'] = metabolites
            self.stats_data_label.config(
                text=f"Metabolites: {self.current_stats['metabolites']} | Samples: {self.current_stats['samples']}"
            )
        
        # 提取樣本數量
        sample_match = re.search(r'樣本[數数量]*[:：\s]*(\d+)', message)
        if sample_match:
            samples = int(sample_match.group(1))
            self.current_stats['samples'] = samples
            self.stats_data_label.config(
                text=f"Metabolites: {self.current_stats['metabolites']} | Samples: {self.current_stats['samples']}"
            )
        
        # 提取輸出檔案路徑
        # 匹配各種可能的輸出路徑格式
        output_patterns = [
            r'輸出[檔文件案]*[:：\s]*(.*?\.xlsx)',
            r'保存[至到]*[:：\s]*(.*?\.xlsx)',
            r'[Ss]aved?\s+(?:to|as)[:：\s]*(.*?\.xlsx)',
            r'[Oo]utput\s+(?:file|path)[:：\s]*(.*?\.xlsx)',
            r'結果檔案[:：\s]*(.*?\.xlsx)',
            r'檔案路徑[:：\s]*(.*?\.xlsx)'
        ]
        
        for pattern in output_patterns:
            output_match = re.search(pattern, message, re.IGNORECASE)
            if output_match:
                output_path = output_match.group(1).strip()
                # 清理路徑中的引號和多餘空白
                output_path = output_path.strip('"\'').strip()
                
                # 驗證路徑是否存在
                if os.path.exists(output_path):
                    self.current_stats['output_path'] = output_path
                    filename = os.path.basename(output_path)
                    self.stats_output_label.config(text=filename)
                    self.open_folder_btn.config(state='normal')
                    self.logger.info(f"✓ 已捕獲輸出路徑: {output_path}")
                    break
                else:
                    # 嘗試相對路徑
                    abs_path = os.path.abspath(output_path)
                    if os.path.exists(abs_path):
                        self.current_stats['output_path'] = abs_path
                        filename = os.path.basename(abs_path)
                        self.stats_output_label.config(text=filename)
                        self.open_folder_btn.config(state='normal')
                        self.logger.info(f"✓ 已捕獲輸出路徑: {abs_path}")
                        break

    def display_log(self, log_record):
        """在GUI中顯示日誌"""
        message = log_record.getMessage()
        level = log_record.levelname
        
        tag = level
        
        self.result_text.insert(tk.END, f"[{level}] {message}\n", tag)
        self.result_text.see(tk.END)

    def update_button_states(self):
        """更新所有按鈕的啟用/禁用狀態"""
        for i, step in enumerate(self.steps):
            dependencies_met = all(
                dep in self.completed_steps 
                for dep in step['dependencies']
            )
            
            if dependencies_met and step['name'] not in self.completed_steps:
                self.step_buttons[i].config(state='normal')
            else:
                if step['name'] in self.completed_steps:
                    self.step_buttons[i].config(state='normal')
                else:
                    self.step_buttons[i].config(state='disabled')

    def load_script(self, script_name):
        """動態且安全地載入腳本"""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(script_dir, f"{script_name}.py")
            
            if not os.path.exists(script_path):
                raise FileNotFoundError(f"找不到腳本: {script_path}")
            
            sys.path.insert(0, script_dir)
            
            spec = importlib.util.spec_from_file_location(script_name, script_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if not hasattr(module, 'main'):
                raise AttributeError(f"腳本 {script_name} 缺少 main() 函數")
            
            return module
        
        except Exception as e:
            self.logger.error(f"載入腳本失敗: {script_name}")
            self.logger.error(traceback.format_exc())
            raise
        
        finally:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            if script_dir in sys.path:
                sys.path.remove(script_dir)

    def select_file_in_main_thread(self, title="選擇檔案", filetypes=None):
        """在主線程中選擇檔案"""
        if filetypes is None:
            filetypes = [("Excel files", "*.xlsx *.xls")]
        
        self.selected_file_path = filedialog.askopenfilename(
            title=title,
            filetypes=filetypes,
            parent=self.master
        )
        
        self.file_selected.set()

    def execute_step(self, step):
        """執行指定步驟的校正"""
        missing_deps = [
            dep for dep in step['dependencies'] 
            if dep not in self.completed_steps
        ]
        
        if missing_deps:
            messagebox.showwarning(
                "無法執行", 
                f"請先完成以下步驟：\n• " + "\n• ".join(missing_deps)
            )
            return
        
        if step['name'] in self.completed_steps:
            confirm = messagebox.askyesno(
                "確認重新執行",
                f"步驟「{step['name']}」已完成，是否要重新執行？"
            )
            if not confirm:
                return
            
            self.remove_step_and_dependents(step['name'])
        
        # 重置統計資訊
        self.current_stats = {
            'step_name': step['name'],
            'file_path': '',
            'metabolites': 0,
            'samples': 0,
            'output_path': ''
        }
        
        self.stats_step_label.config(text=step['name'])
        self.stats_file_label.config(text="未選擇")
        self.stats_data_label.config(text="Metabolites: - | Samples: -")
        self.stats_output_label.config(text="未生成")
        self.open_folder_btn.config(state='disabled')
        
        self.cancel_flag.clear()
        
        # 先在主線程中選擇檔案
        self.logger.info(f"請選擇 {step['name']} 的輸入檔案...")
        self.file_selected.clear()
        self.selected_file_path = None
        
        # 在主線程中顯示檔案選擇對話框
        self.master.after(100, lambda: self.select_file_in_main_thread(
            title=f"選擇 {step['name']} 的輸入檔案",
            filetypes=[("Excel files", "*.xlsx *.xls")]
        ))
        
        # 啟動執行線程（會等待檔案選擇完成）
        self.current_thread = threading.Thread(
            target=self.run_step_in_thread, 
            args=(step,),
            daemon=True
        )
        self.current_thread.start()

    def remove_step_and_dependents(self, step_name):
        """移除步驟及其所有依賴它的後續步驟"""
        self.completed_steps.discard(step_name)
        
        for step in self.steps:
            if step_name in step['dependencies']:
                self.remove_step_and_dependents(step['name'])
        
        for i, step in enumerate(self.steps):
            if step['name'] not in self.completed_steps:
                self.step_status_labels[i].config(
                    text="⚪ 未執行", 
                    foreground="gray"
                )

    def run_step_in_thread(self, step):
        """在線程中執行步驟"""
        result = None
        error_msg = None
        
        try:
            self.master.after(0, lambda s=step: self.on_step_start(s))
            
            self.logger.info("=" * 80)
            self.logger.info(f"開始執行: {step['name']}")
            self.logger.info("=" * 80)
            
            # 等待檔案選擇完成（最多等待60秒）
            if not self.file_selected.wait(timeout=60):
                raise TimeoutError("檔案選擇超時")
            
            # 檢查是否被取消
            if self.cancel_flag.is_set():
                error_msg = "執行被用戶取消"
                self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                return
            
            # 檢查是否選擇了檔案
            if not self.selected_file_path:
                error_msg = "用戶取消了檔案選擇"
                self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                return
            
            self.logger.info(f"已選擇檔案: {os.path.basename(self.selected_file_path)}")
            
            # 更新統計面板的檔案資訊
            self.current_stats['file_path'] = self.selected_file_path
            self.master.after(0, lambda: self.stats_file_label.config(
                text=os.path.basename(self.selected_file_path)
            ))
            
            # 載入腳本
            script_module = self.load_script(step['script'])
            
            if not script_module:
                raise Exception("腳本載入失敗")
            
            # 🔧 捕獲標準輸出和標準錯誤
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            
            # 使用自定義的StreamToLogger來捕獲輸出
            sys.stdout = StreamToLogger(self.logger, logging.INFO)
            sys.stderr = StreamToLogger(self.logger, logging.ERROR)
            
            try:
                # 執行子程式
                result = script_module.main(input_file=self.selected_file_path)
                
            finally:
                # 恢復標準輸出和標準錯誤
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            
            # 檢查是否被取消
            if self.cancel_flag.is_set():
                error_msg = "執行被用戶取消"
                self.master.after(0, lambda s=step, err=error_msg: self.on_step_cancelled(s, err))
                return
            
            # 🔧 嘗試解析結果並更新統計資訊
            if isinstance(result, dict):
                self.logger.info(f"收到返回結果: {result}")
                self.progress_queue.put(result)
            elif result is None:
                self.logger.warning(f"{step['name']} 返回 None，嘗試從日誌中提取資訊")
            
            # 完成
            self.master.after(0, lambda s=step, r=result: self.on_step_complete(s, r))
            
        except Exception as e:
            error_msg = str(e)
            self.logger.error(f"執行失敗: {step['name']}")
            self.logger.error(traceback.format_exc())
            self.master.after(0, lambda s=step, err=error_msg: self.on_step_error(s, err))

    def on_step_start(self, step):
        """步驟開始時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = True
        
        self.step_status_labels[index].config(
            text="🔄 執行中...", 
            foreground=self.color_scheme['running']
        )
        
        for btn in self.step_buttons:
            btn.config(state='disabled')
        
        self.cancel_btn.config(state='normal')

    def on_step_complete(self, step, result):
        """步驟完成時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = False
        
        self.step_status_labels[index].config(
            text="✅ 已完成", 
            foreground=self.color_scheme['success']
        )
        
        self.completed_steps.add(step['name'])
        
        self.logger.info("=" * 80)
        self.logger.info(f"✅ {step['name']} 執行完成！")
        if result and result != True:
            self.logger.info(f"結果: {result}")
        self.logger.info("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')
        
        messagebox.showinfo("完成", f"{step['name']} 已成功執行！")

    def on_step_error(self, step, error):
        """步驟失敗時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = False
        
        self.step_status_labels[index].config(
            text="❌ 失敗", 
            foreground=self.color_scheme['danger']
        )
        
        self.logger.error("=" * 80)
        self.logger.error(f"❌ {step['name']} 執行失敗！")
        self.logger.error(f"錯誤: {error}")
        self.logger.error("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')
        
        retry = messagebox.askyesno(
            "執行失敗", 
            f"{step['name']} 執行失敗：\n{error}\n\n是否要重試？"
        )
        
        if retry:
            self.execute_step(step)

    def on_step_cancelled(self, step, reason=""):
        """步驟被取消時的UI更新"""
        index = self.steps.index(step)
        
        self.is_executing = False
        
        self.step_status_labels[index].config(
            text="⚠️ 已取消", 
            foreground=self.color_scheme['warning']
        )
        
        self.logger.warning("=" * 80)
        self.logger.warning(f"⚠️ {step['name']} 執行已取消")
        if reason:
            self.logger.warning(f"原因: {reason}")
        self.logger.warning("=" * 80)
        
        self.update_button_states()
        
        self.cancel_btn.config(state='disabled')

    def cancel_execution(self):
        """取消執行"""
        if messagebox.askyesno("確認取消", "確定要取消當前執行嗎？"):
            self.cancel_flag.set()
            self.logger.info("用戶請求取消執行")

    def reset_all_steps(self):
        """重置所有步驟"""
        if self.is_executing:
            messagebox.showwarning("無法重置", "有任務正在執行中，請先取消執行")
            return
        
        if messagebox.askyesno(
            "確認重置", 
            "確定要重置所有步驟嗎？\n這將清除所有完成記錄。"
        ):
            self.completed_steps.clear()
            
            for label in self.step_status_labels:
                label.config(text="⚪ 未執行", foreground="gray")
            
            # 重置統計資訊
            self.current_stats = {
                'step_name': '',
                'file_path': '',
                'metabolites': 0,
                'samples': 0,
                'output_path': ''
            }
            
            self.stats_step_label.config(text="等待執行...")
            self.stats_file_label.config(text="未選擇")
            self.stats_data_label.config(text="Metabolites: - | Samples: -")
            self.stats_output_label.config(text="未生成")
            self.open_folder_btn.config(state='disabled')
            
            self.update_button_states()
            
            self.logger.info("🔄 已重置所有步驟")

    def clear_log(self):
        """清除日誌"""
        if messagebox.askyesno("確認清除", "確定要清除日誌顯示嗎？"):
            self.result_text.delete(1.0, tk.END)
            self.logger.info("清除日誌顯示")


# 自定義日誌處理器類
class QueueHandler(logging.Handler):
    """將日誌發送到隊列的處理器"""
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
    
    def emit(self, record):
        self.log_queue.put(record)


# 自定義輸出流類
class StreamToLogger:
    """將標準輸出重定向到日誌系統"""
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''
    
    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())
    
    def flush(self):
        pass


def main():
    root = tk.Tk()
    app = DataNormalizationApp(root)
    
    def on_closing():
        if app.is_executing:
            if messagebox.askokcancel("退出", "有任務正在執行，確定要退出嗎？\n這將強制終止當前任務。"):
                app.cancel_flag.set()
                app.logger.info("程式關閉，強制終止執行")
                root.destroy()
        else:
            app.logger.info("程式正常關閉")
            root.destroy()
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()