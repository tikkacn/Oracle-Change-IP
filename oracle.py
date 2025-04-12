#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import os
import sys

def get_user_input(prompt, default=None):
    """获取用户输入，支持默认值"""
    if default:
        user_input = input(f"{prompt} (默认: {default}): ") or default
    else:
        user_input = input(f"{prompt}: ")
    
    # 如果用户输入n，返回占位符
    if user_input.lower() == 'n':
        return "PLACEHOLDER"
    
    return user_input

def generate_config():
    """生成配置文件"""
    print("欢迎使用甲骨文云监控配置生成器!")
    print("此脚本将引导您创建配置文件。如果对某项不确定，请输入'n'，稍后可手动编辑。")
    print("-" * 50)
    
    # 全局配置
    config = {
        "global": {},
        "accounts": []
    }
    
    # 检查间隔
    round_time = get_user_input("检查间隔时间(秒)", "600")
    config["global"]["round_time"] = int(round_time) if round_time.isdigit() else round_time
    
    # 检测服务URL
    check_url = get_user_input("远程检测服务URL", "http://your-check-server.com/check")
    config["global"]["check_server_url"] = check_url
    
    # 代理设置(可选)
    proxy = get_user_input("代理URL(如不需要请留空)")
    if proxy:
        config["global"]["proxy"] = proxy
    else:
        config["global"]["proxy"] = ""
    
    # 账户信息
    num_accounts = get_user_input("您有几个甲骨文云账户需要监控?", "1")
    try:
        num_accounts = int(num_accounts)
    except ValueError:
        print("输入有误，默认使用1个账户")
        num_accounts = 1
    
    for account_idx in range(1, num_accounts + 1):
        print(f"\n--- 配置账户 {account_idx} ---")
        account = {}
        
        # 账户名称
        account["name"] = get_user_input(f"账户{account_idx}名称", f"oracle-account{account_idx}")
        
        # OCI配置文件路径
        if account_idx == 1:
            default_config_path = "~/.oci/config"
        else:
            default_config_path = f"~/.oci/config{account_idx}"
        account["oci_config_path"] = get_user_input("OCI配置文件路径", default_config_path)
        
        # OCI配置文件配置名
        account["oci_profile"] = get_user_input("OCI配置文件配置名", "DEFAULT")
        
        # 服务器信息
        account["servers"] = []
        num_servers = get_user_input(f"账户{account_idx}中有几个实例需要监控?", "1")
        try:
            num_servers = int(num_servers)
        except ValueError:
            print("输入有误，默认使用1个实例")
            num_servers = 1
        
        for server_idx in range(1, num_servers + 1):
            print(f"\n--- 配置账户{account_idx}的实例{server_idx} ---")
            server = {}
            
            # Compartment ID
            server["compartment_id"] = get_user_input("实例所在的Compartment ID(OCID)")
            
            # 实例ID
            server["instance_id"] = get_user_input("实例ID(OCID)")
            
            # VNIC ID(可选)
            vnic_id = get_user_input("VNIC ID(可留空,程序会自动获取)")
            server["vnic_id"] = vnic_id
            
            # 监控端口
            port = get_user_input("需要监控的端口", "443")
            server["port"] = int(port) if port.isdigit() else port
            
            account["servers"].append(server)
        
        config["accounts"].append(account)
    
    return config

def save_config(config, filename="oci_monitor_config.json"):
    """保存配置到文件"""
    with open(filename, 'w') as f:
        json.dump(config, f, indent=4)
    print(f"\n配置已保存到 {filename}")
    print("如果有任何输入'n'或不确定的部分，请手动编辑文件补充完整。")

def main():
    """主函数"""
    config = generate_config()
    
    # 询问文件名
    filename = get_user_input("保存配置文件的名称", "oci_monitor_config.json")
    
    # 如果文件已存在，询问是否覆盖
    if os.path.exists(filename):
        overwrite = get_user_input(f"文件{filename}已存在，是否覆盖?(y/n)", "n")
        if overwrite.lower() != 'y':
            filename = f"new_{filename}"
    
    save_config(config, filename)
    
    # 展示配置
    print("\n以下是生成的配置文件内容:")
    print("-" * 50)
    print(json.dumps(config, indent=4))
    print("-" * 50)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n配置生成已取消")
        sys.exit(1)
