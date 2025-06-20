import discord
from discord.ext import commands, tasks
import json
import asyncio
from datetime import datetime, time
import os
import uuid
from typing import Optional, List
import pytz

# 日本時間の設定
JST = pytz.timezone('Asia/Tokyo')

# Botの設定
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 通知データを保存するファイル
NOTIFICATIONS_FILE = 'notifications.json'

# 曜日の日本語マッピング
WEEKDAYS = {
    '月': 0, '火': 1, '水': 2, '木': 3, '金': 4, '土': 5, '日': 6,
    '月曜': 0, '火曜': 1, '水曜': 2, '木曜': 3, '金曜': 4, '土曜': 5, '日曜': 6,
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
}

WEEKDAY_NAMES = ['月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日', '日曜日']

class NotificationBot:
    def __init__(self):
        self.notifications = self.load_notifications()
        self.sent_notifications = set()  # 一回限り通知の送信済み管理
    
    def load_notifications(self):
        """保存された通知データを読み込み"""
        try:
            with open(NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_notifications(self):
        """通知データを保存"""
        with open(NOTIFICATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.notifications, f, ensure_ascii=False, indent=2)
    
    def add_notification(self, channel_id: int, time_str: str, message: str, 
                        weekdays: Optional[List[int]] = None, repeat: bool = True) -> str:
        """新しい通知を追加"""
        channel_key = str(channel_id)
        if channel_key not in self.notifications:
            self.notifications[channel_key] = []
        
        # ユニークIDを生成
        notification_id = str(uuid.uuid4())[:8]
        
        # 全曜日指定の場合（毎日）
        if weekdays is None:
            weekdays = list(range(7))
        
        notification = {
            'id': notification_id,
            'time': time_str,
            'message': message,
            'weekdays': weekdays,
            'repeat': repeat,
            'enabled': True,
            'created_at': datetime.now(JST).isoformat()
        }
        
        self.notifications[channel_key].append(notification)
        self.save_notifications()
        return notification_id
    
    def remove_notification(self, channel_id: int, notification_id: str) -> Optional[dict]:
        """IDで通知を削除"""
        channel_key = str(channel_id)
        if channel_key not in self.notifications:
            return None
        
        for i, notif in enumerate(self.notifications[channel_key]):
            if notif['id'] == notification_id:
                removed = self.notifications[channel_key].pop(i)
                self.save_notifications()
                return removed
        return None
    
    def toggle_notification(self, channel_id: int, notification_id: str) -> Optional[bool]:
        """通知の有効/無効を切り替え"""
        channel_key = str(channel_id)
        if channel_key not in self.notifications:
            return None
        
        for notif in self.notifications[channel_key]:
            if notif['id'] == notification_id:
                notif['enabled'] = not notif['enabled']
                self.save_notifications()
                return notif['enabled']
        return None
    
    def get_notifications(self, channel_id: int) -> List[dict]:
        """チャンネルの通知一覧を取得"""
        channel_key = str(channel_id)
        return self.notifications.get(channel_key, [])
    
    def should_send_notification(self, notification: dict) -> bool:
        """通知を送信すべきかチェック"""
        if not notification['enabled']:
            return False
        
        now = datetime.now(JST)  # 日本時間を使用
        current_weekday = now.weekday()
        current_time = now.strftime('%H:%M')
        
        # 時間チェック
        if notification['time'] != current_time:
            return False
        
        # 曜日チェック
        if current_weekday not in notification['weekdays']:
            return False
        
        # 一回限り通知の場合
        if not notification['repeat']:
            key = f"{notification['id']}_{now.strftime('%Y-%m-%d')}"
            if key in self.sent_notifications:
                return False
            self.sent_notifications.add(key)
        
        return True

# NotificationBotインスタンスを作成
notification_bot = NotificationBot()

@bot.event
async def on_ready():
    print(f'{bot.user} としてログインしました！')
    check_notifications.start()

def parse_weekdays(weekday_str: str) -> List[int]:
    """曜日文字列を解析して数値リストに変換"""
    if not weekday_str or weekday_str.lower() in ['毎日', 'everyday', 'daily']:
        return list(range(7))
    
    weekdays = []
    parts = weekday_str.replace('、', ',').replace(' ', '').split(',')
    
    for part in parts:
        part = part.strip()
        if part in WEEKDAYS:
            weekdays.append(WEEKDAYS[part])
    
    return sorted(list(set(weekdays))) if weekdays else list(range(7))

@bot.command(name='通知追加')
async def add_notification(ctx, time_str: str, repeat_type: str, weekdays_str: str = "毎日", *, message: str):
    """
    通知を追加するコマンド
    使用例: 
    !通知追加 14:30 毎回 月,水,金 会議の時間です
    !通知追加 09:00 一回 火 明日は重要な会議があります
    !通知追加 18:00 毎回 毎日 お疲れさまでした
    """
    try:
        # 時間の形式をチェック
        time_obj = datetime.strptime(time_str, '%H:%M').time()
        
        # 繰り返しタイプをチェック
        if repeat_type not in ['毎回', '一回', 'repeat', 'once']:
            await ctx.send("❌ 繰り返しタイプは `毎回` または `一回` で指定してください。")
            return
        
        repeat = repeat_type in ['毎回', 'repeat']
        
        # 曜日を解析
        weekdays = parse_weekdays(weekdays_str)
        
        if not weekdays:
            await ctx.send("❌ 曜日の指定が正しくありません。\n例: `月,水,金` または `毎日`")
            return
        
        notification_id = notification_bot.add_notification(
            ctx.channel.id, time_str, message, weekdays, repeat
        )
        
        # 曜日の表示文字列を作成
        if len(weekdays) == 7:
            weekday_display = "毎日"
        else:
            weekday_display = ", ".join([WEEKDAY_NAMES[w] for w in weekdays])
        
        repeat_display = "毎回実行" if repeat else "一回のみ"
        
        embed = discord.Embed(
            title="✅ 通知が追加されました",
            color=discord.Color.green()
        )
        embed.add_field(name="ID", value=f"`{notification_id}`", inline=True)
        embed.add_field(name="時間", value=time_str, inline=True)
        embed.add_field(name="実行タイプ", value=repeat_display, inline=True)
        embed.add_field(name="曜日", value=weekday_display, inline=False)
        embed.add_field(name="メッセージ", value=message, inline=False)
        
        await ctx.send(embed=embed)
            
    except ValueError:
        await ctx.send("❌ 時間の形式が正しくありません。HH:MM形式で入力してください。\n例: `!通知追加 14:30 毎回 月,水,金 メッセージ`")

@bot.command(name='通知一覧')
async def list_notifications(ctx):
    """登録されている通知の一覧を表示"""
    notifications = notification_bot.get_notifications(ctx.channel.id)
    
    if not notifications:
        await ctx.send("📭 このチャンネルには通知が登録されていません。")
        return
    
    embed = discord.Embed(
        title="📋 登録済み通知一覧",
        color=discord.Color.blue()
    )
    
    for notif in notifications:
        status = "🟢 有効" if notif['enabled'] else "🔴 無効"
        repeat_type = "🔄 毎回" if notif['repeat'] else "1️⃣ 一回"
        
        # 曜日表示
        if len(notif['weekdays']) == 7:
            weekday_display = "毎日"
        else:
            weekday_display = ", ".join([WEEKDAY_NAMES[w] for w in notif['weekdays']])
        
        field_name = f"ID: {notif['id']} | {notif['time']} | {status} {repeat_type}"
        field_value = f"**曜日:** {weekday_display}\n**メッセージ:** {notif['message']}"
        
        embed.add_field(
            name=field_name,
            value=field_value,
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='通知削除')
async def remove_notification(ctx, notification_id: str):
    """
    通知を削除するコマンド
    使用例: !通知削除 a1b2c3d4
    """
    removed = notification_bot.remove_notification(ctx.channel.id, notification_id)
    
    if removed:
        weekday_display = "毎日" if len(removed['weekdays']) == 7 else ", ".join([WEEKDAY_NAMES[w] for w in removed['weekdays']])
        
        embed = discord.Embed(
            title="🗑️ 通知が削除されました",
            color=discord.Color.orange()
        )
        embed.add_field(name="ID", value=f"`{removed['id']}`", inline=True)
        embed.add_field(name="時間", value=removed['time'], inline=True)
        embed.add_field(name="曜日", value=weekday_display, inline=True)
        embed.add_field(name="メッセージ", value=removed['message'], inline=False)
        
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ 指定されたIDの通知が見つかりません。`!通知一覧`で確認してください。")

@bot.command(name='通知切替')
async def toggle_notification(ctx, notification_id: str):
    """
    通知の有効/無効を切り替えるコマンド
    使用例: !通知切替 a1b2c3d4
    """
    result = notification_bot.toggle_notification(ctx.channel.id, notification_id)
    
    if result is not None:
        status = "有効" if result else "無効"
        color = discord.Color.green() if result else discord.Color.red()
        
        embed = discord.Embed(
            title=f"🔄 通知を{status}にしました",
            description=f"ID: `{notification_id}`",
            color=color
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ 指定されたIDの通知が見つかりません。")

@bot.command(name='通知ヘルプ')
async def notification_help(ctx):
    """ヘルプメッセージを表示"""
    embed = discord.Embed(
        title="🔔 高機能通知Bot ヘルプ",
        description="このBotで使用できるコマンド一覧",
        color=discord.Color.purple()
    )
    
    commands_info = [
        ("!通知追加 [時間] [毎回/一回] [曜日] [メッセージ]", 
         "新しい通知を追加\n例: `!通知追加 14:30 毎回 月,水,金 会議の時間です`\n例: `!通知追加 09:00 一回 火 重要な会議`"),
        ("!通知一覧", "登録されている通知の一覧を表示"),
        ("!通知削除 [ID]", "指定したIDの通知を削除\n例: `!通知削除 a1b2c3d4`"),
        ("!通知切替 [ID]", "指定したIDの通知を有効/無効切り替え\n例: `!通知切替 a1b2c3d4`"),
        ("!通知ヘルプ", "このヘルプメッセージを表示")
    ]
    
    for command, description in commands_info:
        embed.add_field(name=command, value=description, inline=False)
    
    embed.add_field(
        name="📅 曜日の指定方法",
        value="• `毎日` - 毎日実行\n• `月,水,金` - 月水金のみ\n• `土,日` - 週末のみ\n• `月曜,火曜` - フル表記も可能",
        inline=False
    )
    
    embed.add_field(
        name="🔄 実行タイプ",
        value="• `毎回` - 指定した曜日・時間に毎回実行\n• `一回` - 指定した曜日・時間に一回のみ実行",
        inline=False
    )
    
    embed.set_footer(text="時間は24時間形式（HH:MM）で入力してください")
    await ctx.send(embed=embed)

@tasks.loop(seconds=30)  # 30秒ごとにチェック
async def check_notifications():
    """定期的に現在時刻をチェックして通知を送信"""
    for channel_id, notifications in notification_bot.notifications.items():
        try:
            channel = bot.get_channel(int(channel_id))
            if not channel:
                continue
                
            for notification in notifications:
                if notification_bot.should_send_notification(notification):
                    
                    # 曜日表示
                    now = datetime.now(JST)  # 日本時間を使用
                    weekday_name = WEEKDAY_NAMES[now.weekday()]
                    
                    embed = discord.Embed(
                        title="🔔 通知時間です！",
                        description=notification['message'],
                        color=discord.Color.gold(),
                        timestamp=datetime.now(JST)
                    )
                    
                    embed.add_field(
                        name="📅 今日",
                        value=f"{weekday_name} {now.strftime('%H:%M')}",
                        inline=True
                    )
                    
                    embed.add_field(
                        name="🔄 タイプ",
                        value="毎回実行" if notification['repeat'] else "一回のみ",
                        inline=True
                    )
                    
                    embed.set_footer(text=f"ID: {notification['id']}")
                    
                    await channel.send(embed=embed)
                    
        except Exception as e:
            print(f"通知送信エラー: {e}")

# Botエラーハンドリング
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ 必要な引数が不足しています。`!通知ヘルプ`でコマンドの使い方を確認してください。")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ 引数の形式が正しくありません。`!通知ヘルプ`でコマンドの使い方を確認してください。")
    else:
        await ctx.send("❌ エラーが発生しました。もう一度お試しください。")
        print(f"エラー: {error}")

# Botを実行
if __name__ == "__main__":
    # 環境変数からトークンを取得、または直接指定
    TOKEN = os.getenv('DISCORD_BOT_TOKEN') or 'YOUR_BOT_TOKEN_HERE'
    
    if TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("⚠️  Botトークンを設定してください")
        print("環境変数 DISCORD_BOT_TOKEN を設定するか、")
        print("コード内の TOKEN 変数に直接トークンを入力してください")
    else:
        bot.run(TOKEN)