from pathlib import Path  # 用于读写文件路径
import os, base64  # os 生成随机盐值，base64 转换 key 格式
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes  # 这里用到 SHA256
from cryptography.fernet import Fernet, InvalidToken  # Fernet 负责对称加解密

from src.config import cfg
from src.util import FileDecryptError

encrypt_image_path = Path(__file__).parents[1] / "encrypt_image"
if not encrypt_image_path.exists():
    encrypt_image_path.mkdir(
        parents=True,
        exist_ok=True
    )

def save_image(file_name: str, data: bytes) -> None:
    (encrypt_image_path / file_name).write_bytes(data)

def load_encrypted_image(file_name: str) -> bytes:
    return (encrypt_image_path / file_name).read_bytes()

# make_key：把 token_a + token_b + salt 变成 Fernet 能用的 key
def make_key(token_a: str, token_b: str, salt: bytes) -> bytes:
    material = (token_a + "-" + token_b).encode("utf-8")  # 两个 token 合并成原始密钥材料
    kdf = HKDF(  # 创建 HKDF 对象
        algorithm=hashes.SHA256(),  # 指定哈希算法为 SHA256
        length=32,  # 输出 32 字节密钥
        salt=salt,  # 每次随机盐值，防止相同输入得到相同 key
        info=b"proxyblindimg-v1",  # 上下文标签，区分不同业务用途
    )
    key = kdf.derive(material)  # 派生出二进制密钥
    return base64.urlsafe_b64encode(key)  # Fernet 需要 urlsafe base64 格式

# encrypt_image：传入原图字节并加密，输出为“salt + 密文”
def encrypt_image(img_bytes: bytes, token: str) -> str:
    salt = os.urandom(16)  # 生成 16 字节随机盐值
    key = make_key(cfg.token, token, salt)  # 用 token 和 salt 派生本次 key
    encrypted = Fernet(key).encrypt(img_bytes)  # 加密图片字节
    file_name = base64.urlsafe_b64encode(os.urandom(12)).decode("ascii")  # 12字节=>16字符
    save_image(
        file_name=file_name,
        data=(salt + encrypted)
    )  # 把 salt 放前面，解密时要用
    return file_name

# decrypt_image：读取加密文件，拆出 salt 后解密恢复原始字节
def decrypt_image(file_name: str, token: str) -> bytes:
    raw = load_encrypted_image(file_name)
    if len(raw) < 17:
        raise FileDecryptError("Encrypted data is invalid: payload too short")

    salt, encrypted = raw[:16], raw[16:]  # 前 16 字节是 salt，后面是密文
    key = make_key(cfg.token, token, salt)  # 必须用同样 token 和 salt 才能算出同一 key
    try:
        return Fernet(key).decrypt(encrypted)  # 解密得到原始图片字节
    except InvalidToken as e:
        raise FileDecryptError("Decrypt failed: token mismatch or corrupted data") from e