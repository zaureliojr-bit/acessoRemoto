"""Demonstração visual local: não importa nem executa o aplicativo de acesso remoto."""
import tkinter as tk
from tkinter import ttk, messagebox

def main():
    root = tk.Tk()
    root.title("DrogaLink Remote — Demonstração")
    root.resizable(False, False)
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground="#164E63")
    style.configure("Subtitle.TLabel", foreground="#475569")
    style.configure("Value.TLabel", font=("Segoe UI", 11, "bold"))
    container = ttk.Frame(root, padding=20)
    container.pack(fill="both", expand=True)
    ttk.Label(container, text="DrogaLink Remote", style="Title.TLabel").pack(anchor="w")
    ttk.Label(container, text="Suporte autorizado • Prévia visual sem conexões", style="Subtitle.TLabel").pack(anchor="w", pady=(0, 16))
    def notice():
        messagebox.showinfo("Demonstração", "Este controle é apenas visual. Nenhuma conexão é iniciada.")
    def button(parent, text, row, col, **grid):
        ttk.Button(parent, text=text, command=notice).grid(row=row, column=col, **grid)
    host = ttk.LabelFrame(container, text="Receber suporte autorizado", padding=10)
    host.pack(fill="x", pady=(0, 10))
    ttk.Label(host, text="Seu IP na rede local:").grid(row=0, column=0, sticky="w")
    ttk.Label(host, text="192.0.2.10 (exemplo)", style="Value.TLabel").grid(row=0, column=1, padx=8, sticky="w")
    button(host, "Copiar", 0, 2, sticky="e")
    ttk.Label(host, text="Senha de acesso:").grid(row=1, column=0, sticky="w", pady=8)
    ttk.Entry(host, width=20, show="*", textvariable=tk.StringVar(value="000000"), state="readonly").grid(row=1, column=1, padx=8, sticky="w")
    button(host, "Copiar", 1, 2, sticky="e")
    button(host, "Gerar nova senha", 2, 0, columnspan=3, sticky="w")
    ttk.Label(host, text="Recebimento desativado — demonstração", style="Subtitle.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=8)
    button(host, "Ativar recebimento", 4, 0, sticky="w")
    ttk.Button(host, text="Encerrar aplicativo", command=root.destroy).grid(row=4, column=1, columnspan=2, sticky="e")
    ttk.Label(host, text="Nenhum canal autenticado ativo", foreground="#B91C1C").grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
    client = ttk.LabelFrame(container, text="Solicitar conexão a outro computador", padding=10)
    client.pack(fill="x", pady=(0, 10))
    ttk.Label(client, text="IP do computador remoto:").grid(row=0, column=0, sticky="w")
    ttk.Entry(client, width=25).grid(row=0, column=1, padx=8)
    ttk.Label(client, text="Senha:").grid(row=1, column=0, sticky="w", pady=8)
    ttk.Entry(client, width=25, show="*").grid(row=1, column=1, padx=8)
    button(client, "Conectar", 2, 0, sticky="w")
    button(client, "Limpar histórico", 2, 1, sticky="e")
    ttk.Label(container, text="Versão experimental • Interface demonstrativa", style="Subtitle.TLabel").pack(anchor="w")
    root.mainloop()

if __name__ == "__main__":
    main()
