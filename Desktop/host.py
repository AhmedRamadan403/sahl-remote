"""Sahl Remote desktop: pairing and a separate, window-owned app download page."""
import contextlib
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
import webbrowser

import customtkinter as ctk
from PIL import Image, ImageDraw
import qrcode
from qrcode.constants import ERROR_CORRECT_M

from host_worker import HostWorker, resource_directory
from downloads import DownloadWorker
from pairing import discover_host, normalize_code, pairing_url
from shutdown import WindowShutdown
from windows_platform import WindowsDesktop

BG, CARD, EDGE, TEXT, MUTED, LIME = "#101416", "#1a2224", "#344346", "#eff5f2", "#9aadae", "#cdfc6c"


def ui_font(size, bold=False, family="Segoe UI"):
    return ctk.CTkFont(family=family, size=size, weight="bold" if bold else "normal")


class HostWindow:
    def __init__(self, root, desktop):
        self.root, self.desktop = root, desktop
        self.events = queue.Queue()
        self.worker = None
        self.download_worker = None
        self.download_window = None
        self.download_url = tk.StringVar(value="Starting the download page…")
        self.download_ready = False
        self.closing = self.ready = self.connected = self.searching = False
        self.pending_id = None
        self.fingerprint = ""
        self.ip = "127.0.0.1"
        self.actual_port = 8443
        self.code = tk.StringVar(value="--------")
        self.code_display = tk.StringVar(value="----  ----")
        self.address = tk.StringVar(value="Start sharing to get your local address")
        self.port = tk.StringVar(value="8443")
        self.status = tk.StringVar(value="Offline · desktop access is off")
        self.notice = tk.StringVar(value="One Wi-Fi network. One approved connection. You're in control.")

        root.title("Sahl Remote | Connect. Scan. Go.")
        root.configure(fg_color=BG)
        window_scale = root._get_window_scaling()
        height = max(500, min(730, int((root.winfo_screenheight()-90)/window_scale)))
        compact = min(1.0, height/700)
        ctk.set_widget_scaling(compact)
        root.geometry(f"1060x{height}")
        root.minsize(int(960*compact), int(min(height,650)))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<Control-q>", lambda _: self.close())
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(root, width=156, corner_radius=0, fg_color="#161d1f")
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        ctk.CTkLabel(sidebar, text="↗", font=ui_font(34, bold=True, family="Segoe UI"), text_color=BG, fg_color=LIME, corner_radius=16, width=54, height=54).pack(anchor="w", padx=23, pady=(28,12))
        ctk.CTkLabel(sidebar, text="sahl\nremote", font=ui_font(25, bold=True, family="Segoe UI"), justify="left", text_color=TEXT).pack(anchor="w", padx=23)
        ctk.CTkLabel(sidebar, text="YOUR SPACE.\nANY SCREEN.", justify="left", font=ui_font(10, bold=False, family="Segoe UI"), text_color=MUTED).pack(anchor="w", padx=24, pady=(12,30))
        ctk.CTkLabel(sidebar, text="  ↗   Connection", font=ui_font(12, bold=True, family="Segoe UI"), text_color=LIME, fg_color="#28342b", corner_radius=11, width=132, height=42).pack(padx=12)
        ctk.CTkLabel(sidebar, text="  ◇   Local & private", font=ui_font(11, bold=False, family="Segoe UI"), text_color=MUTED).pack(anchor="w",padx=20,pady=15)
        self.download_button=ctk.CTkButton(sidebar,text="↓  Get the apps",font=ui_font(12,True),fg_color="#28342b",hover_color="#384c34",text_color=LIME,width=132,height=40,corner_radius=11,command=self.show_downloads)
        self.download_button.pack(padx=12,pady=(3,0))
        ctk.CTkLabel(sidebar, text="LOCAL EDITION\nv0.3.1 / WEB DOWNLOADS", justify="left", font=ui_font(9, bold=False, family="Segoe UI"), text_color=MUTED).pack(side="bottom",anchor="w",padx=23,pady=25)

        main=ctk.CTkFrame(root,fg_color="transparent")
        main.grid(row=0,column=1,sticky="nsew",padx=25,pady=24)
        main.grid_columnconfigure((0,1),weight=1,uniform="main")
        main.grid_rowconfigure(2,weight=1)
        ctk.CTkLabel(main,text="Connect. Scan. Go.",font=ui_font(29, bold=True, family="Segoe UI"),text_color=TEXT,anchor="w").grid(row=0,column=0,columnspan=2,sticky="w")
        ctk.CTkLabel(main,text="Your Windows desktop, a little closer to every screen.",font=ui_font(12, bold=False, family="Segoe UI"),text_color=MUTED,anchor="w").grid(row=1,column=0,columnspan=2,sticky="w",pady=(3,18))

        self.qr_card=self.card(main)
        self.qr_card.grid(row=2,column=0,sticky="nsew",padx=(0,10))
        ctk.CTkLabel(self.qr_card,text="01 / PHONE",height=14,font=ui_font(10, bold=True, family="Segoe UI"),text_color=LIME).pack(anchor="w",padx=22,pady=(18,6))
        ctk.CTkLabel(self.qr_card,text="Scan to connect.",font=ui_font(22, bold=True, family="Segoe UI"),text_color=TEXT).pack(anchor="w",padx=22)
        ctk.CTkLabel(self.qr_card,text="Open Sahl on your phone.\nPoint the camera at this QR.",font=ui_font(12, bold=False, family="Segoe UI"),text_color=MUTED,justify="left").pack(anchor="w",padx=22,pady=(7,12))
        self.qr_label=ctk.CTkLabel(self.qr_card,text="Start sharing\nto generate your QR",font=ui_font(14, bold=True, family="Segoe UI"),text_color="#59706b",fg_color="#e9f0e9",corner_radius=16,width=220,height=220)
        self.qr_label.pack(expand=True,pady=8,padx=14)
        ctk.CTkLabel(self.qr_card,text="Encrypted pairing · expires in 5 minutes",height=14,font=ui_font(10, bold=False, family="Segoe UI"),text_color=MUTED).pack(pady=(10,18))

        right=ctk.CTkFrame(main,fg_color="transparent")
        right.grid(row=2,column=1,sticky="nsew",padx=(10,0))
        right.grid_columnconfigure(0,weight=1)
        right.grid_rowconfigure(1,weight=1)
        self.code_card=self.card(right,height=205)
        self.code_card.grid(row=0,column=0,sticky="ew")
        self.code_card.grid_propagate(False)
        self.code_body=ctk.CTkFrame(self.code_card,fg_color="transparent")
        self.code_body.pack(fill="both",expand=True,padx=20,pady=16)
        ctk.CTkLabel(self.code_body,text="02 / COMPUTER",font=ui_font(10, bold=True, family="Segoe UI"),text_color=LIME).pack(anchor="w")
        ctk.CTkLabel(self.code_body,text="Your connection code",font=ui_font(17, bold=True, family="Segoe UI"),text_color=TEXT).pack(anchor="w",pady=(7,2))
        ctk.CTkLabel(self.code_body,textvariable=self.code_display,font=ui_font(34, bold=True, family="Consolas"),text_color=LIME).pack(anchor="w",pady=3)
        self.copy_code_button=ctk.CTkButton(self.code_body,text="Copy code  ↗",width=130,height=31,fg_color="#2a3730",hover_color="#344b36",text_color=LIME,command=self.copy_code,state="disabled")
        self.copy_code_button.pack(anchor="w",pady=(5,0))

        self.approval_body=ctk.CTkFrame(self.code_card,fg_color="transparent")
        ctk.CTkLabel(self.approval_body,text="CONNECTION REQUEST",text_color=LIME,font=ui_font(11, bold=True, family="Segoe UI")).pack(anchor="w")
        self.request_label=ctk.CTkLabel(self.approval_body,text="",text_color=TEXT,font=ui_font(12, bold=False, family="Segoe UI"),justify="left",wraplength=275)
        self.request_label.pack(anchor="w",pady=8)
        approve_buttons=ctk.CTkFrame(self.approval_body,fg_color="transparent")
        approve_buttons.pack(fill="x",pady=5)
        ctk.CTkButton(approve_buttons,text="Allow device",fg_color=LIME,hover_color="#b5e35b",text_color=BG,width=132,height=36,command=lambda:self.decide(True)).pack(side="left")
        ctk.CTkButton(approve_buttons,text="Deny",fg_color="#3d3e38",hover_color="#56574d",width=70,height=36,command=lambda:self.decide(False)).pack(side="left",padx=8)

        connect=self.card(right)
        connect.grid(row=1,column=0,sticky="nsew",pady=(15,0))
        ctk.CTkLabel(connect,text="Connect to a computer",font=ui_font(17, bold=True, family="Segoe UI"),text_color=TEXT).pack(anchor="w",padx=20,pady=(17,5))
        ctk.CTkLabel(connect,text="Enter its 8-digit code. We'll find it\non your local Wi-Fi.",font=ui_font(11, bold=False, family="Segoe UI"),text_color=MUTED,justify="left").pack(anchor="w",padx=20,pady=(0,12))
        self.remote_code=ctk.CTkEntry(connect,placeholder_text="0000 0000",height=43,font=ui_font(20, bold=False, family="Consolas"),justify="center",fg_color=BG,border_color=EDGE,corner_radius=11)
        self.remote_code.pack(fill="x",padx=20)
        self.remote_code.bind("<Return>",lambda _:self.connect_number())
        self.connect_button=ctk.CTkButton(connect,text="Connect  →",height=37,fg_color="#2b383c",hover_color="#3b5055",text_color=TEXT,font=ui_font(12, bold=True, family="Segoe UI"),command=self.connect_number)
        self.connect_button.pack(fill="x",padx=20,pady=(10,17))

        footer=ctk.CTkFrame(main,fg_color="transparent")
        footer.grid(row=3,column=0,columnspan=2,sticky="ew",pady=(17,0))
        self.start_button=ctk.CTkButton(footer,text="Start sharing  ↗",height=44,width=190,corner_radius=12,fg_color=LIME,hover_color="#b8e65d",text_color=BG,font=ui_font(13, bold=True, family="Segoe UI"),command=self.start)
        self.start_button.pack(side="left")
        self.stop_button=ctk.CTkButton(footer,text="Stop sharing",height=44,width=135,corner_radius=12,fg_color="#3c2c2b",hover_color="#60413c",text_color="#ffb49e",command=self.stop,state="disabled")
        self.stop_button.pack(side="left",padx=10)
        self.exit_button=ctk.CTkButton(footer,text="خروج  ×",height=44,width=100,corner_radius=12,fg_color="#58352f",hover_color="#79463c",text_color="#ffd2bf",font=ui_font(13,True),command=self.close)
        self.exit_button.pack(side="right",padx=(12,0))
        self.port_box=ctk.CTkEntry(footer,width=64,height=32,textvariable=self.port,fg_color=CARD,border_color=EDGE,justify="center")
        self.port_box.pack(side="right")
        ctk.CTkLabel(footer,text="Port",text_color=MUTED,font=ui_font(11, bold=False, family="Segoe UI")).pack(side="right",padx=9)
        ctk.CTkLabel(main,textvariable=self.status,height=16,text_color=LIME,font=ui_font(11, bold=True, family="Segoe UI"),anchor="w").grid(row=4,column=0,columnspan=2,sticky="ew",pady=(12,3))
        self.address_label=ctk.CTkLabel(main,textvariable=self.address,height=16,text_color=MUTED,font=ui_font(10, bold=False, family="Consolas"),anchor="w",cursor="hand2")
        self.address_label.grid(row=5,column=0,columnspan=2,sticky="ew")
        self.address_label.bind("<Button-1>",lambda _:self.copy_address())
        self.notice_label=ctk.CTkLabel(main,textvariable=self.notice,height=16,font=ui_font(10, bold=False, family="Segoe UI"),text_color=MUTED,wraplength=740,justify="left",anchor="w")
        self.notice_label.grid(row=6,column=0,columnspan=2,sticky="ew",pady=(5,0))
        root.after(80,self.poll)

    def card(self,parent,**kwargs):
        return ctk.CTkFrame(parent,fg_color=CARD,border_width=1,border_color=EDGE,corner_radius=20,**kwargs)

    def show_downloads(self):
        if self.download_window and self.download_window.winfo_exists():
            self.download_window.lift()
            return
        window=self.download_window=ctk.CTkToplevel(self.root)
        window.title("Sahl Remote | Download the apps")
        window.configure(fg_color=BG)
        download_height=max(450,min(690,int((window.winfo_screenheight()-100)/window._get_window_scaling())))
        window.geometry(f"540x{download_height}")
        window.minsize(450,min(540,download_height))
        window.transient(self.root)
        ctk.CTkLabel(window,text="Get Sahl on every screen.",font=ui_font(24,True),text_color=TEXT).pack(padx=22,pady=(25,4))
        ctk.CTkLabel(window,text="افتح كاميرا الموبايل وامسح الكود لتحميل التطبيق",font=ui_font(14),text_color=LIME).pack(padx=18,pady=(1,7))
        ctk.CTkLabel(window,text="Android APK + Windows EXE · same Wi-Fi network",font=ui_font(11),text_color=MUTED).pack(pady=(0,16))
        self.download_qr_label=ctk.CTkLabel(window,text="Starting…",width=220,height=220,fg_color="#ffffff",text_color="#3d5546",corner_radius=15,font=ui_font(13,True))
        self.download_qr_label.pack(pady=5)
        self.download_address_box=ctk.CTkEntry(window,textvariable=self.download_url,width=450,height=36,font=ui_font(12,family="Consolas"),justify="center",state="readonly",fg_color=CARD,border_color=EDGE)
        self.download_address_box.pack(fill="x",padx=28,pady=(17,12))
        buttons=ctk.CTkFrame(window,fg_color="transparent")
        buttons.pack(pady=0)
        ctk.CTkButton(buttons,text="Open page  ↗",width=150,height=38,fg_color=LIME,hover_color="#b5e35b",text_color=BG,command=self.open_downloads).pack(side="left",padx=5)
        ctk.CTkButton(buttons,text="Copy link",width=120,height=38,fg_color="#2b383c",hover_color="#3b5055",command=self.copy_download_url).pack(side="left",padx=5)
        self.download_toggle=ctk.CTkButton(window,text="Stop downloads",height=33,width=160,fg_color="#3c2c2b",hover_color="#60413c",text_color="#ffb49e",command=self.toggle_downloads)
        self.download_toggle.pack(pady=(18,9))
        ctk.CTkButton(window,text="خروج من البرنامج  ×",height=34,width=200,fg_color="#58352f",hover_color="#79463c",text_color="#ffd2bf",command=self.close).pack(pady=(0,9))
        ctk.CTkLabel(window,text="خلي الكمبيوتر مفتوح والجهازين على نفس الواي فاي.\nDownload access ends when you close Sahl Remote.\nScreen sharing has its own Start / Stop buttons.",font=ui_font(11),text_color=MUTED,justify="center",wraplength=440).pack(padx=22,pady=(0,16))
        if self.download_ready:self.update_download_qr()
        else:self.start_downloads()

    def start_downloads(self):
        if self.download_worker and self.download_worker.thread.is_alive():return
        self.download_url.set("Starting the download page…")
        self.download_worker=DownloadWorker(self.events,resource_directory())
        self.download_worker.start()
        if self.download_window and self.download_window.winfo_exists():
            self.download_toggle.configure(text="Stop downloads")
            self.download_qr_label.configure(text="Starting…",image=None)

    def toggle_downloads(self):
        if self.download_worker and self.download_worker.thread.is_alive():
            self.download_worker.stop()
            self.download_toggle.configure(state="disabled",text="Stopping…")
        else:self.start_downloads()

    def update_download_qr(self):
        if not self.download_window or not self.download_window.winfo_exists():return
        image=qrcode.make(self.download_url.get()).convert("RGB")
        self.download_qr_image=ctk.CTkImage(light_image=image,dark_image=image,size=(208,208))
        self.download_qr_label.configure(image=self.download_qr_image,text="")
        self.download_toggle.configure(text="Stop downloads",state="normal")

    def open_downloads(self):
        if self.download_ready:webbrowser.open(self.download_url.get())

    def copy_download_url(self):
        if self.download_ready:
            self.root.clipboard_clear();self.root.clipboard_append(self.download_url.get())
            self.notice.set("Download link copied. Open it on any device connected to the same Wi-Fi.")

    def copy_code(self):
        if self.ready:
            self.root.clipboard_clear();self.root.clipboard_append(self.code.get())
            self.notice.set("Code copied. Enter it in Sahl Remote on the other computer.")

    def copy_address(self):
        if self.ready:
            self.root.clipboard_clear();self.root.clipboard_append(self.address.get())
            self.notice.set("Local address copied. The browser also supports manual code entry.")

    def update_qr(self):
        if not self.ready or self.connected or self.pending_id:
            text="Session in progress" if self.connected else "Waiting for approval" if self.pending_id else "Start sharing\nto generate your QR"
            self.qr_label.configure(image=None,text=text)
            return
        if not self.fingerprint or len(self.code.get())!=8:return
        url=pairing_url(self.ip,self.actual_port,self.code.get(),self.fingerprint)
        qr=qrcode.QRCode(error_correction=ERROR_CORRECT_M,box_size=8,border=4)
        qr.add_data(url);qr.make(fit=True)
        image=qr.make_image(fill_color="#101416",back_color="#ffffff").convert("RGB")
        self.qr_image=ctk.CTkImage(light_image=image,dark_image=image,size=(208,208))
        self.qr_label.configure(image=self.qr_image,text="")

    def start(self):
        if self.worker and self.worker.thread.is_alive():return
        try:
            port=int(self.port.get())
            if not 1024<=port<=65535:raise ValueError()
        except ValueError:
            self.notice.set("Choose a port from 1024 to 65535.");return
        self.start_button.configure(state="disabled");self.stop_button.configure(state="normal");self.port_box.configure(state="disabled")
        self.status.set("Starting · preparing encrypted local access")
        self.worker=HostWorker(self.events,self.desktop,port);self.worker.start()

    def stop(self):
        self.stop_button.configure(state="disabled");self.status.set("Stopping · ending remote access")
        self.pending_id=None;self.restore_connection_card()
        if self.worker:self.worker.stop()

    def decide(self,accepted):
        request_id,self.pending_id=self.pending_id,None
        self.restore_connection_card()
        if request_id and self.worker:self.worker.approve(request_id,accepted)

    def restore_connection_card(self):
        self.approval_body.pack_forget()
        if not self.code_body.winfo_manager():self.code_body.pack(fill="both",expand=True,padx=20,pady=16)

    def connect_number(self):
        if self.searching:return
        code=normalize_code(self.remote_code.get())
        if len(code)!=8:self.notice.set("Enter the complete 8-digit code from the other computer.");return
        self.searching=True;self.connect_button.configure(state="disabled",text="Searching…")
        self.notice.set("Looking for the computer on your local network…")
        def find():
            try:self.events.put({"type":"found",**discover_host(code)})
            except Exception as error:self.events.put({"type":"lookup_failed","message":str(error)[:240]})
        threading.Thread(target=find,daemon=True,name="Sahl local lookup").start()

    def poll(self):
        if self.closing:return
        try:self.process_events()
        except Exception as error:
            with contextlib.suppress(tk.TclError):self.notice.set("Window update failed: " + str(error)[:160])
        finally:
            if not self.closing:self.root.after(80,self.poll)

    def process_events(self):
        try:
            while True:
                event=self.events.get_nowait();kind=event["type"]
                if kind=="downloads_ready":
                    self.download_ready=True;self.download_url.set(event["url"]);self.update_download_qr()
                    self.download_button.configure(text="●  App downloads")
                elif kind=="downloads_failure":
                    self.download_url.set("Download page could not start")
                    self.notice.set(event["message"])
                elif kind=="downloads_stopped":
                    self.download_ready=False;self.download_button.configure(text="↓  Get the apps")
                    if self.download_url.get()!="Download page could not start":self.download_url.set("Downloads are off")
                    if self.download_window and self.download_window.winfo_exists():
                        self.download_qr_label.configure(image=None,text="Downloads are off")
                        self.download_toggle.configure(text="Start downloads",state="normal")
                elif kind=="code":
                    raw=event["code"];self.code.set(raw);self.code_display.set(raw[:4]+"  "+raw[4:]);self.update_qr()
                elif kind=="certificate":self.fingerprint=event["fingerprint"]
                elif kind=="listening":
                    self.ready=True;self.connected=False;self.actual_port=event["port"];self.ip=(event["addresses"] or ["127.0.0.1"])[0]
                    self.address.set(f"https://{self.ip}:{self.actual_port}");self.status.set("Ready · scan QR or share the connection code")
                    self.copy_code_button.configure(state="normal");self.update_qr()
                    self.notice.set("Phone: scan with the Flutter app. Computer: enter the code in Sahl Remote.")
                elif kind=="approval":
                    self.pending_id=event["id"];self.code_body.pack_forget();self.approval_body.pack(fill="both",expand=True,padx=20,pady=16)
                    self.request_label.configure(text=f"{event['name']}\n{event['ip']}\nAllow screen and keyboard access?")
                    self.update_qr();self.root.lift();self.root.bell()
                elif kind=="approval_expired":
                    if self.pending_id==event["id"]:self.pending_id=None;self.restore_connection_card();self.update_qr()
                elif kind=="connected":
                    self.pending_id=None;self.connected=True;self.restore_connection_card();self.update_qr()
                    self.status.set(f"Sharing · {event['name']} ({event['ip']})")
                    self.notice.set("A device can see this screen. Stop sharing ends access and closes the listener.")
                elif kind=="screen_paused":
                    self.status.set("الجلسة متصلة · في انتظار رجوع سطح المكتب")
                    self.notice.set(event["message"])
                elif kind=="screen_resumed":
                    self.status.set("Sharing · desktop available again")
                    self.notice.set("رجعت الشاشة. تقدر تكمل من نفس الجلسة.")
                elif kind=="disconnected":
                    self.connected=False;self.status.set("Ready · device disconnected; desktop access is off");self.update_qr()
                elif kind in ("notice","failure"):self.notice.set(event["message"])
                elif kind=="stopped":
                    self.ready=self.connected=False;self.pending_id=None;self.restore_connection_card();self.code.set("--------");self.code_display.set("----  ----")
                    self.address.set("Start sharing to get your local address");self.start_button.configure(state="normal");self.stop_button.configure(state="disabled");self.port_box.configure(state="normal");self.copy_code_button.configure(state="disabled")
                    self.status.set("Offline · desktop access is off");self.update_qr()
                elif kind in ("found","lookup_failed"):
                    self.searching=False;self.connect_button.configure(state="normal",text="Connect  →")
                    if kind=="found":webbrowser.open(event["url"]);self.notice.set("Computer found. Continue in the browser; the host will ask for approval.")
                    else:self.notice.set(event["message"])
        except queue.Empty:pass

    def close(self):
        if self.closing:return
        self.closing=True
        self.exit_button.configure(state="disabled",text="جاري الإغلاق…")
        self.status.set("Closing · ending sharing and downloads")
        self.shutdown=WindowShutdown(self.root,(self.worker,self.download_worker),self.desktop.release_all)
        self.shutdown.start()


def main(start_downloads=False):
    desktop=WindowsDesktop()
    ctk.set_appearance_mode("dark")
    root=ctk.CTk()
    icon=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parent))/"sahl.ico"
    if icon.exists():
        with contextlib.suppress(tk.TclError):root.iconbitmap(default=str(icon))
    window=HostWindow(root,desktop)
    if start_downloads:root.after(250,window.show_downloads)
    root.mainloop()
