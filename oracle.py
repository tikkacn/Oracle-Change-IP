#!/usr/bin/env python
# -*- coding: utf-8 -*-
import time
import os
import sys
import json
import logging
import requests
import threading
import oci
from oci.config import from_file

# 定义日志格式
level = logging.INFO
logging.basicConfig(
    level=level, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建默认配置
def create_default_config():
    config_file = "oci_monitor_config.json"
    default_config = {
        "global": {
            "round_time": 600,
            "check_server_url": "http://8.130.42.117:5000/check",  # 远程检测服务地址
            "proxy": ""
        },
        "accounts": [
            {
                "name": "account1",
                "oci_config_path": "~/.oci/config",  # OCI配置文件路径
                "oci_profile": "DEFAULT",  # OCI配置文件中的配置名
                "servers": [
                    {
                        "compartment_id": "ocid1.compartment.oc1..example",  # 实例所在的compartment ID
                        "instance_id": "ocid1.instance.oc1..example",  # 实例ID
                        "vnic_id": "",  # 留空，程序会自动获取主VNIC的ID
                        "port": 443  # 监控的端口
                    }
                ]
            }
        ]
    }
    with open(config_file, "w") as f:
        json.dump(default_config, f, indent=4)
    return default_config

# 读取配置文件
def load_config():
    config_file = "oci_monitor_config.json"
    try:
        if not os.path.exists(config_file):
            logger.error(f"配置文件 {config_file} 不存在，创建默认配置")
            config = create_default_config()
            logger.error(f"请更新 {config_file} 文件并重启程序")
            sys.exit(1)
        else:
            with open(config_file, "r") as f:
                config = json.load(f)
            
            # 设置代理（如果有）
            proxy_url = config["global"].get("proxy", "")
            if proxy_url:
                os.environ["http_proxy"] = proxy_url
                os.environ["https_proxy"] = proxy_url
                
            return config
                    
    except Exception as e:
        logger.error(f"读取配置错误: {str(e)}")
        sys.exit(1)

# 初始化OCI客户端
def init_oci_clients(oci_config_path, oci_profile):
    try:
        # 加载OCI配置
        config = from_file(file_location=os.path.expanduser(oci_config_path), profile_name=oci_profile)
        
        # 创建客户端
        compute_client = oci.core.ComputeClient(config)
        network_client = oci.core.VirtualNetworkClient(config)
        
        return compute_client, network_client
    except Exception as e:
        logger.error(f"初始化OCI客户端失败: {str(e)}")
        raise

# 检查服务器连接状态类
class CheckConnection:
    # 远程检测服务
    @staticmethod
    def remote_check(ip, port, check_server_url):
        """
        使用远程检测服务检查IP和端口可达性
        """
        try:
            url = check_server_url
            # 使用server而不是ip作为参数名，以兼容自建服务
            params = {"server": ip, "port": port}
            logger.debug(f"发送远程检测请求: {url} 参数: {params}")
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                # 尝试解析纯文本响应，预期是"True"或"False"
                text = response.text.strip()
                if text == "True":
                    return True
                elif text == "False":
                    return False
                else:
                    logger.error(f"无法解析远程检测服务响应: {response.text}")
                    return False
            else:
                logger.error(f"远程检测服务返回状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"远程检测请求失败: {str(e)}")
            return False

# Oracle Cloud API操作类
class OCIAPI:
    def __init__(self, server_config, compute_client, network_client):
        self.compartment_id = server_config["compartment_id"]
        self.instance_id = server_config["instance_id"]
        self.vnic_id = server_config["vnic_id"]
        self.port = server_config["port"]
        self.compute_client = compute_client
        self.network_client = network_client
        
        # 创建实例专用的IP历史记录文件名
        self.ip_history_file = f"ip_history_oci_{self.instance_id[-8:]}.txt"
        
        # 如果未提供vnic_id，自动获取
        if not self.vnic_id:
            self.vnic_id = self._get_primary_vnic_id()
    
    # 获取主VNIC的ID
    def _get_primary_vnic_id(self):
        try:
            logger.info(f"获取实例 {self.instance_id} 的主VNIC...")
            vnic_attachments = self.compute_client.list_vnic_attachments(
                compartment_id=self.compartment_id,
                instance_id=self.instance_id
            ).data
            
            # 找到主VNIC
            for vnic_attachment in vnic_attachments:
                if vnic_attachment.lifecycle_state == "ATTACHED":
                    vnic_id = vnic_attachment.vnic_id
                    logger.info(f"找到主VNIC: {vnic_id}")
                    return vnic_id
            
            raise Exception("未找到附加到实例的VNIC")
        except Exception as e:
            logger.error(f"获取主VNIC失败: {str(e)}")
            raise
    
    # 记录IP地址历史
    def record_ip(self, ip):
        if ip and ip not in self.read_ip():
            with open(self.ip_history_file, "a") as f:
                f.write(ip + "\n")
    
    # 读取IP地址历史
    def read_ip(self):
        ip_list = []
        if not os.path.exists(self.ip_history_file):
            with open(self.ip_history_file, "w") as f:
                return []
        else:
            with open(self.ip_history_file, "r") as f:
                for line in f.readlines():
                    ip_list.append(line.strip())
        return ip_list
    
    # 获取当前公共IP
    def get_ip(self):
        try:
            logger.info(f"获取VNIC {self.vnic_id} 的公共IP...")
            vnic = self.network_client.get_vnic(vnic_id=self.vnic_id).data
            
            # 检查是否有公共IP
            if vnic.public_ip:
                logger.info(f"当前公共IP: {vnic.public_ip}")
                return vnic.public_ip
            else:
                logger.info("VNIC没有公共IP")
                return None
        except Exception as e:
            logger.error(f"获取公共IP失败: {str(e)}")
            return None
    
    # 更换公共IP
    def change_ip(self):
        try:
            logger.info(f"开始更换公共IP: {self.instance_id}")
            
            # 获取当前VNIC信息
            vnic = self.network_client.get_vnic(vnic_id=self.vnic_id).data
            old_ip = vnic.public_ip if vnic.public_ip else "未分配"
            
            # 如果已有公共IP，解除分配
            if vnic.public_ip:
                logger.info(f"解除当前公共IP: {vnic.public_ip}")
                # 获取当前公共IP的OCID
                public_ips = self.network_client.list_public_ips(
                    scope="REGION",
                    compartment_id=self.compartment_id
                ).data
                
                public_ip_id = None
                for ip in public_ips:
                    if ip.ip_address == vnic.public_ip:
                        public_ip_id = ip.id
                        break
                
                if public_ip_id:
                    # 解除公共IP
                    self.network_client.delete_public_ip(public_ip_id=public_ip_id)
                    # 等待IP释放
                    time.sleep(10)
                else:
                    logger.warning(f"未找到公共IP {vnic.public_ip} 的ID")
            
            # 分配新的临时公共IP
            logger.info("分配新的公共IP...")
            create_public_ip_details = oci.core.models.CreatePublicIpDetails(
                compartment_id=self.compartment_id,
                lifetime="EPHEMERAL",
                private_ip_id=vnic.private_ip_id
            )
            
            # 创建新的公共IP
            public_ip = self.network_client.create_public_ip(
                create_public_ip_details=create_public_ip_details
            ).data
            
            # 等待新IP生效
            time.sleep(15)
            
            # 获取新的公共IP
            new_vnic = self.network_client.get_vnic(vnic_id=self.vnic_id).data
            new_ip = new_vnic.public_ip
            
            # 记录新IP
            self.record_ip(new_ip)
            
            logger.info(f"IP地址已从 {old_ip} 更换为 {new_ip}")
            return old_ip, new_ip
            
        except Exception as e:
            logger.error(f"更换公共IP失败: {str(e)}")
            raise

# 监控单个服务器
def monitor_server(server_config, global_config, compute_client, network_client, account_name="default"):
    try:
        # 初始化OCI API
        oci = OCIAPI(server_config, compute_client, network_client, account_name)
        
        # 服务器标识
        server_info = f"账户 {account_name} 实例 {oci.instance_id[-8:]}"
        logger.info(f"开始监控服务器: {server_info}")
        
        # 检测服务配置
        check_server_url = global_config.get("check_server_url", "")
        if not check_server_url:
            logger.error("未配置检测服务URL，请在配置中设置check_server_url")
            return
        
        while True:
            try:
                # 获取当前IP
                ip = oci.get_ip()
                if not ip:
                    logger.warning(f"服务器 {server_info} 未分配公共IP，尝试分配...")
                    try:
                        old_ip, ip = oci.change_ip()
                        logger.info(f"服务器 {server_info} 已分配IP: {ip}")
                    except Exception as e:
                        logger.error(f"分配IP失败: {str(e)}")
                        time.sleep(global_config.get("round_time", 600))
                        continue
                
                # 检查连接状态
                logger.info(f"检查服务器 {server_info} ({ip}:{oci.port}) 连接状态...")
                logger.info(f"使用远程检测服务: {check_server_url}")
                reachable = CheckConnection.remote_check(ip, oci.port, check_server_url)
                
                if reachable:
                    logger.info(f"服务器 {server_info} ({ip}:{oci.port}) 连接正常")
                else:
                    logger.warning(f"服务器 {server_info} ({ip}:{oci.port}) 连接失败，尝试更换IP...")
                    try:
                        old_ip, new_ip = oci.change_ip()
                        logger.info(f"服务器 {server_info} IP已更换: 旧IP: {old_ip} -> 新IP: {new_ip}")
                        
                        # 立即检测新IP是否可用
                        logger.info(f"立即检测新IP {new_ip} 是否可用...")
                        new_ip_reachable = CheckConnection.remote_check(new_ip, oci.port, check_server_url)
                        
                        if new_ip_reachable:
                            logger.info(f"新IP {new_ip} 连接正常")
                        else:
                            logger.warning(f"新IP {new_ip} 连接仍然失败，将在下一轮尝试再次更换")
                    except Exception as e:
                        logger.error(f"服务器 {server_info} 更换IP失败: {str(e)}")
                
                # 等待下一轮检查
                time.sleep(global_config.get("round_time", 600))
                
            except Exception as e:
                logger.error(f"监控服务器 {server_info} 时发生错误: {str(e)}")
                time.sleep(global_config.get("round_time", 600))
                
    except Exception as e:
        logger.error(f"初始化服务器 {server_config['instance_id']} 监控失败: {str(e)}")

# 主程序
if __name__ == "__main__":
    try:
        # 加载配置
        config = load_config()
        global_config = config["global"]
        accounts = config["accounts"]
        
        # 设置代理（如果有）
        proxy_url = global_config.get("proxy", "")
        if proxy_url:
            os.environ["http_proxy"] = proxy_url
            os.environ["https_proxy"] = proxy_url
        
        # 启动多线程监控
        threads = []
        
        # 为每个账户创建监控线程
        for account in accounts:
            account_name = account["name"]
            oci_config_path = account["oci_config_path"]
            oci_profile = account["oci_profile"]
            servers = account["servers"]
            
            logger.info(f"初始化账户: {account_name}")
            
            try:
                # 初始化OCI客户端
                compute_client, network_client = init_oci_clients(
                    oci_config_path,
                    oci_profile
                )
                
                # 为每个服务器创建监控线程
                for server_config in servers:
                    thread = threading.Thread(
                        target=monitor_server,
                        args=(server_config, global_config, compute_client, network_client, account_name),
                        daemon=True,
                        name=f"{account_name}-{server_config['instance_id'][-8:]}"
                    )
                    threads.append(thread)
                    thread.start()
                    logger.info(f"已启动账户 {account_name} 服务器 {server_config['instance_id'][-8:]} 的监控线程")
            except Exception as e:
                logger.error(f"初始化账户 {account_name} 失败: {str(e)}")
                continue
        
        # 等待所有线程结束（除非手动终止）
        for thread in threads:
            thread.join()
            
    except Exception as e:
        logger.error(f"主程序错误: {str(e)}")
        time.sleep(10)
        sys.exit(1)
