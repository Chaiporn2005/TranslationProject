import customtkinter as ctk
import pyautogui
import easyocr
import numpy as np
import deepl
import keyboard
import tkinter as tk
from tkinter import messagebox
from tkinter import simpledialog
from PIL import Image
import threading
import json
import os
import cv2

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"api_key": ""}

def save_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f)

# โหลด EasyOCR ตามโหมดภาษา
LANG_MODE_CONFIG = {
    "EN → TH": {"ocr_langs": ["en"],       "deepl_source": "EN"},
    "JA → TH": {"ocr_langs": ["ja"],       "deepl_source": "JA"},
    "ES → TH": {"ocr_langs": ["es", "en"], "deepl_source": "ES"},
}

# โหลด reader ทุกภาษาไว้ล่วงหน้า (หรือจะโหลดตอนเปลี่ยนโหมดก็ได้)
readers = {}
for mode, cfg in LANG_MODE_CONFIG.items():
    readers[mode] = easyocr.Reader(cfg["ocr_langs"])


class OverlayResult(tk.Toplevel):
    instances = []

    def __init__(self, master, x, y, w, h, text):
        super().__init__(master)
        OverlayResult.instances.append(self)
        self.overrideredirect(True)
        
        # ตั้งจุดเกิดให้ตรงกับข้อความ (x, y) แล้วให้หน้าต่างขยายกล่องข้อความอัตโนมัติ
        self.geometry(f"+{x-5}+{y-5}")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.9)
        
        # ตัดคำของข้อความที่ยาวกว่ากล่องเดิมเล็กน้อย
        wrap_w = max(w + 20, 100)
        label = tk.Label(self, text=text, wraplength=wrap_w, bg="#1e1e1e", fg="white",
                         font=("Leelawadee UI", 11, "bold"), padx=5, pady=5)
        label.pack(fill="both", expand=True)
        label.bind("<Button-1>", lambda e: self.destroy())

    def destroy(self):
        if self in OverlayResult.instances:
            OverlayResult.instances.remove(self)
        super().destroy()

    @classmethod
    def clear_all(cls):
        for instance in list(cls.instances):
            try:
                instance.destroy()
            except:
                pass
        cls.instances.clear()

class TextResultWindow(ctk.CTkToplevel):
    def __init__(self, master, results_list):
        super().__init__(master)
        self.title("ผลลัพธ์การแปลจากรูปภาพ")
        self.geometry("600x400")
        self.attributes("-topmost", True)
        
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        
        for orig, translated in results_list:
            frame = ctk.CTkFrame(scroll)
            frame.pack(fill="x", pady=5)
            lbl_orig = ctk.CTkLabel(frame, text=orig, text_color="gray", justify="left", font=("Leelawadee UI", 12))
            lbl_orig.pack(anchor="w", padx=10, pady=(5, 0))
            lbl_trans = ctk.CTkLabel(frame, text=translated, justify="left", font=("Leelawadee UI", 14, "bold"), wraplength=500)
            lbl_trans.pack(anchor="w", padx=10, pady=(0, 5))

class SnippingTool:
    def __init__(self, callback):
        self.callback = callback
        self.snip_surface = tk.Toplevel()
        self.snip_surface.attributes('-alpha', 0.3, '-fullscreen', True, "-topmost", True)
        self.snip_surface.overrideredirect(True)
        self.canvas = tk.Canvas(self.snip_surface, cursor="cross", bg="grey")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.snip_surface.bind("<Escape>", self.on_cancel)
        self.canvas.bind("<ButtonPress-3>", self.on_cancel) # คลิกขวายกเลิกได้ด้วย
        self.start_x = self.start_y = 0
        self.rect = None

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline='red', width=2)

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        x1, y1, x2, y2 = self.start_x, self.start_y, event.x, event.y
        self.snip_surface.destroy()
        self.callback(min(x1, x2), min(y1, y2), abs(x1-x2), abs(y1-y2))

    def on_cancel(self, event):
        self.snip_surface.destroy()
        # ส่งค่า 0 เพื่อข้ามการแปลและเรียกหน้าต่างหลักกลับมาทันที
        self.callback(0, 0, 0, 0)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Screen AI Translator")
        self.geometry("450x360")  # สูงขึ้นนิดหน่อยเพื่อรองรับ segmented button

        self.current_hotkey = "ctrl+alt+b"
        self.is_listening = False
        self.current_mode = "EN → TH"  # โหมดเริ่มต้น

        self.config = load_config()
        
        # เคลียร์รหัส API เก่า (Default Key เดิม) ที่อาจจะค้างติดอยู่ในไฟล์ config ของผู้ใช้
        if self.config.get("api_key", "").strip() == "8e821959-1d78-409b-bad5-5c53665b0e22:fx":
            self.config["api_key"] = ""
            save_config(self.config)
            
        self.update_translator()

        # --- Title ---
        self.label_title = ctk.CTkLabel(self, text="Translation From Screen", font=("Leelawadee UI", 20, "bold"))
        self.label_title.pack(pady=(15, 5))

        # --- Segmented Button เลือกโหมดภาษา ---
        self.label_mode = ctk.CTkLabel(self, text="โหมดการแปล", font=("Leelawadee UI", 12), text_color="gray")
        self.label_mode.pack()

        self.seg_mode = ctk.CTkSegmentedButton(
            self,
            values=list(LANG_MODE_CONFIG.keys()),
            command=self.on_mode_change,
            font=("Leelawadee UI", 13, "bold"),
            width=380,
            height=38,
        )
        self.seg_mode.set(self.current_mode)
        self.seg_mode.pack(pady=(4, 12))

        # --- ส่วนปุ่มหลัก ---
        self.frame_body = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_body.pack(fill="both", expand=True)

        # ฝั่งซ้าย
        self.frame_main = ctk.CTkFrame(self.frame_body, fg_color="transparent")
        self.frame_main.pack(side="left", padx=30, fill="y")

        self.btn_snip = ctk.CTkButton(self.frame_main, text="กดเพื่ออัดหน้าจอ", height=60, width=200,
                                       command=self.start_snipping)
        self.btn_snip.pack(pady=10)

        self.btn_select = ctk.CTkButton(self.frame_main, text="เลือกรูปภาพ", height=60, width=200,
                                         command=self.select_image_file)
        self.btn_select.pack(pady=10)

        # ฝั่งขวา
        self.frame_side = ctk.CTkFrame(self.frame_body, fg_color="transparent")
        self.frame_side.pack(side="right", padx=30, fill="y")

        self.btn_api_key = ctk.CTkButton(self.frame_side, text="API Key",
                                         height=35, width=120, command=self.set_api_key)
        self.btn_api_key.pack(pady=(15, 10))

        self.btn_setting = ctk.CTkButton(self.frame_side, text=f"ตั้งค่าปุ่ม\n({self.current_hotkey})",
                                          height=50, width=120, command=self.change_hotkey)
        self.btn_setting.pack(pady=(5, 30))

        self.update_hotkey()
        
        # แจ้งเตือนถ้ายาวังไม่ได้ตั้ง API Key
        if not self.config.get("api_key", "").strip():
            self.after(500, lambda: messagebox.showwarning("แจ้งเตือน", "ข้อกำหนดการใช้งาน:\nแอปพลิเคชันนี้จำเป็นต้องใช้ DeepL API Key ของคุณเองในการแปลรบกวนตั้งค่าที่ปุ่ม 'API Key' ด้วยครับ"))

    def update_translator(self):
        key = self.config.get("api_key", "").strip()
        if not key:
            self.translator = None
        else:
            try:
                self.translator = deepl.Translator(key)
            except Exception as e:
                messagebox.showerror("ข้อผิดพลาด", f"API Key ไม่ถูกต้อง: {e}")
                self.translator = None

    def set_api_key(self):
        prompt = "กรุณาใส่ DeepL API Key ของคุณ\n(สามารถสมัครได้ฟรีที่ https://auth.deepl.com/login)"
        new_key = simpledialog.askstring("ตั้งค่า DeepL API Key", prompt, initialvalue=self.config.get("api_key", ""))
        if new_key is not None:
            self.config["api_key"] = new_key.strip()
            save_config(self.config)
            self.update_translator()
            messagebox.showinfo("สำเร็จ", "บันทึก API Key เรียบร้อยแล้ว")

    def on_mode_change(self, selected_mode):
        self.current_mode = selected_mode
        print(f"เปลี่ยนโหมดเป็น: {self.current_mode}")

    def start_snipping(self):
        OverlayResult.clear_all()  # ลบผลลัพธ์เก่าบนหน้าจอก่อนแคปใหม่
        self.withdraw()
        self.after(200, lambda: SnippingTool(self.process_capture))

    def select_image_file(self):
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            title="เลือกรูปภาพที่ต้องการแปล",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp")]
        )
        if not file_path:
            return

        # ตรวจสอบเรื่องรหัส API
        if not self.config.get("api_key", "").strip() or self.translator is None:
            messagebox.showerror("แจ้งเตือน", "ไม่มีรหัส API Key ของ DeepL\nกรุณาใส่รหัสในช่องทางขวาและกดบันทึกเพื่อเริ่มใช้งาน")
            return

        self.btn_select.configure(text="กำลังแปล...", state="disabled")
        self.update()

        def do_process_image():
            try:
                img_pil = Image.open(file_path).convert('RGB')
                img_np = np.array(img_pil)

                cfg = LANG_MODE_CONFIG[self.current_mode]
                reader = readers[self.current_mode]
                source_lang = cfg["deepl_source"]

                # === Image Pre-processing ===
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                
                # เพิ่มความคมชัด (Sharpening) แทน Threshold เพื่อถนอมรายละเอียดตัวอักษร
                kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
                sharpened = cv2.filter2D(gray, -1, kernel)

                # --- เรียกใช้ Reader พร้อมพารามิเตอร์ช่วยชีวิต ---
                results = reader.readtext(
                    sharpened, 
                    detail=1, 
                    paragraph=True,      # รวมคำเป็นประโยค (ช่วยให้ DeepL แปลรู้เรื่องขึ้น)
                    contrast_ths=0.1,    # ยอมรับตัวอักษรที่สีกลืนกับพื้นหลังมากขึ้น
                    adjust_contrast=0.7, 
                    text_threshold=0.7,  # กรองเอาเฉพาะที่มั่นใจจริงๆ
                    rotation_info=[90, 180, 270] 
                )

                texts_to_translate = []
                for item in results:
                    # ถ้า paragraph=True ค่าที่ได้จะเป็น (bbox, text) ไม่มี prob
                    text = item[1]
                    if text.strip() and len(text) > 2:
                        texts_to_translate.append(text)

                if texts_to_translate:
                    translated_results = self.translator.translate_text(
                        texts_to_translate,
                        source_lang=source_lang,
                        target_lang="TH"
                    )
                    
                    if not isinstance(translated_results, list):
                        translated_results = [translated_results]
                    
                    pairs = []
                    for text_orig, res in zip(texts_to_translate, translated_results):
                        pairs.append((text_orig, res.text))
                    
                    def show_results():
                        TextResultWindow(self, pairs)
                        self.btn_select.configure(text="เลือกรูปภาพ", state="normal")
                    self.after(0, show_results)
                else:
                    self.after(0, lambda: messagebox.showinfo("ผลลัพธ์", "ไม่พบข้อความในรูปภาพ"))
                    self.after(0, lambda: self.btn_select.configure(text="เลือกรูปภาพ", state="normal"))
            except Exception as e:
                print(f"Error: {e}")
                self.after(0, lambda: messagebox.showerror("ข้อผิดพลาด", f"เกิดข้อผิดพลาด: {str(e)}"))
                self.after(0, lambda: self.btn_select.configure(text="เลือกรูปภาพ", state="normal"))

        threading.Thread(target=do_process_image, daemon=True).start()

    def process_capture(self, x, y, w, h):
        self.deiconify()
        if w < 5 or h < 5:
            return

        # ตรวจสอบเรื่องรหัส API ก่อน
        if not self.config.get("api_key", "").strip() or self.translator is None:
            messagebox.showerror("แจ้งเตือน", "ไม่มีรหัส API Key ของ DeepL\nกรุณาไปที่ 'API Key' แล้วใส่รหัสของคุณเพื่อเริ่มใช้งาน")
            self.set_api_key()
            return

        # โชว์สถานะกำลังอ่านข้อความ เพื่อแก้ปัญหาผู้ใช้คิดว่าโปรแกรมไม่ทำงานในครั้งแรก
        self.btn_snip.configure(text="กำลังแปล...", state="disabled")
        self.update()

        def do_process():
            try:
                cfg = LANG_MODE_CONFIG[self.current_mode]
                reader = readers[self.current_mode]
                source_lang = cfg["deepl_source"]

                screenshot = pyautogui.screenshot(region=(x, y, w, h))
                img_np = np.array(screenshot)

                # === Image Pre-processing ===
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                h_orig, w_orig = gray.shape
                
                # ขยายรูปและทำ Sharpen แบบเดียวกับโหมดเลือกไฟล์ภาพ
                resized = cv2.resize(gray, (w_orig * 2, h_orig * 2), interpolation=cv2.INTER_CUBIC)
                kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
                sharpened = cv2.filter2D(resized, -1, kernel)

                results = reader.readtext(
                    sharpened, 
                    detail=1, 
                    paragraph=True,
                    contrast_ths=0.1,    
                    adjust_contrast=0.7, 
                    text_threshold=0.7,
                    rotation_info=[90, 180, 270], 
                    mag_ratio=1.2
                )

                texts_to_translate = []
                bboxes = []

                for item in results:
                    bbox = item[0]
                    text = item[1]
                    if text.strip():
                        texts_to_translate.append(text)
                        xs = [pt[0] / 2.0 for pt in bbox]
                        ys = [pt[1] / 2.0 for pt in bbox]
                        x1, x2 = min(xs), max(xs)
                        y1, y2 = min(ys), max(ys)
                        bx = int(x + x1)
                        by = int(y + y1)
                        bw = int(x2 - x1)
                        bh = int(y2 - y1)
                        bboxes.append((bx, by, bw, bh))

                if texts_to_translate:
                    translated_results = self.translator.translate_text(
                        texts_to_translate,
                        source_lang=source_lang,
                        target_lang="TH"
                    )
                    
                    if not isinstance(translated_results, list):
                        translated_results = [translated_results]
                    
                    def show_results():
                        for text_orig, (bx, by, bw, bh), res in zip(texts_to_translate, bboxes, translated_results):
                            print(f"[{self.current_mode}] OCR: {text_orig}")
                            print(f"[{self.current_mode}] แปล: {res.text}")
                            OverlayResult(self, bx, by, bw, bh, res.text)
                        self.btn_snip.configure(text="กดเพื่ออัดหน้าจอ", state="normal")
                    self.after(0, show_results)
                else:
                    self.after(0, lambda: self.btn_snip.configure(text="กดเพื่ออัดหน้าจอ", state="normal"))
            except Exception as e:
                print(f"Error: {e}")
                self.after(0, lambda: self.btn_snip.configure(text="กดเพื่ออัดหน้าจอ", state="normal"))

        threading.Thread(target=do_process, daemon=True).start()

    def update_hotkey(self):
        keyboard.unhook_all()
        keyboard.add_hotkey(self.current_hotkey, self.start_snipping)
        # กด ESC เพื่อลบกล่องแปลข้อความออก
        keyboard.add_hotkey("esc", lambda: self.after(0, OverlayResult.clear_all))

    def change_hotkey(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("ตั้งค่า Hotkey")
        dialog.geometry("320x220")
        dialog.attributes("-topmost", True)
        dialog.resizable(False, False)
        dialog.grab_set()

        pressed_keys = []
        current_combo = []

        ctk.CTkLabel(dialog, text="กดปุ่มที่ต้องการ (ค้างเพื่อเพิ่มปุ่มถัดไป)",
                     font=("Leelawadee UI", 13)).pack(pady=(20, 8))

        key_display = ctk.CTkLabel(dialog, text="รอรับปุ่ม...",
                                    font=("Leelawadee UI", 18, "bold"),
                                    fg_color=("gray85", "gray20"),
                                    corner_radius=8, width=260, height=45)
        key_display.pack(pady=6)

        ctk.CTkLabel(dialog, text="ค้างปุ่มไว้เพื่อเพิ่ม + ปุ่มถัดไป (สูงสุด 3 ปุ่ม)",
                     font=("Leelawadee UI", 11), text_color="gray").pack(pady=4)

        btn_save = ctk.CTkButton(dialog, text="บันทึก", width=260, height=40,
                                  state="disabled", command=lambda: confirm())
        btn_save.pack(pady=(8, 0))

        def normalize_key(key_name):
            aliases = {
                "left ctrl": "ctrl", "right ctrl": "ctrl",
                "left shift": "shift", "right shift": "shift",
                "left alt": "alt", "right alt": "alt",
                "left windows": "win", "right windows": "win",
            }
            return aliases.get(key_name.lower(), key_name.lower())

        def update_display(keys, holding=False):
            if keys:
                display_text = " + ".join(k.upper() for k in keys)
                if holding:
                    display_text += "  +"
                key_display.configure(text=display_text)
            else:
                key_display.configure(text="รอรับปุ่ม...")

        def on_key_down(event):
            key = normalize_key(event.name)
            if key not in pressed_keys:
                if len(pressed_keys) >= 3:
                    return
                pressed_keys.append(key)

            holding = len(pressed_keys) < 3
            dialog.after(0, lambda: update_display(pressed_keys[:], holding=holding))

            if len(pressed_keys) == 3:
                current_combo.clear()
                current_combo.extend(pressed_keys[:])
                dialog.after(0, lambda: update_display(current_combo, holding=False))
                dialog.after(0, lambda: btn_save.configure(state="normal"))

        def on_key_up(event):
            key = normalize_key(event.name)
            modifiers = {"ctrl", "shift", "alt", "win"}
            if key not in modifiers and pressed_keys:
                current_combo.clear()
                current_combo.extend(pressed_keys[:])
                dialog.after(0, lambda: update_display(current_combo, holding=False))
                dialog.after(0, lambda: btn_save.configure(state="normal"))
            if key in pressed_keys:
                pressed_keys.remove(key)

        def confirm():
            if not current_combo:
                return
            hotkey_str = "+".join(current_combo)
            keyboard.unhook_all()
            self.current_hotkey = hotkey_str
            self.btn_setting.configure(text=f"ตั้งค่าปุ่ม\n({self.current_hotkey})")
            self.update_hotkey()
            print(f"เปลี่ยน Hotkey เป็น: {self.current_hotkey}")
            dialog.destroy()

        def on_dialog_close():
            keyboard.unhook_all()
            self.update_hotkey()
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        keyboard.unhook_all()
        keyboard.on_press(on_key_down)
        keyboard.on_release(on_key_up)


if __name__ == "__main__":
    app = App()
    app.mainloop()