# Tokoya

Tokoya（床屋、英語では *barber*）は、Blender 5.1用のヘアースタイリング拡張です。グレースケールの頭皮マスクから毛を植え、Settle Hair Backでロングストレート向けに初期整形し、メッシュで切りそろえます。

## 主な機能

- 白＝0 cm、黒＝最大長のUVペイントマスク
- 4,000本を既定値とする面積一様な植毛
- 長さに応じて9～13点を自動選択するストランド
- 根元2セグメントを最長毛基準で揃えるNatural Root Spacing
- Hair / Body / Clothes / Cutter の明示選択
- v0.6.3: `Settle Hair Back`をSurface Deform後の表示座標で処理
- v0.6.2: 旧`Simulate`ボタンを`Settle Hair Back`へ置換
- Settle実行時、Body用の穴埋めCollider Proxyが無ければ自動生成
- Body ProxyとClothesを使ったCPU BVH初期整形
- `Mesh Shrink`による平面・球などを使ったカット
- `Urchin Reset`による直毛状態への復帰

セルフコリジョンは実装していません。

## 必要環境

- Blender 5.1以降
- Windows x64

## インストール

1. [Releases](../../releases)から最新の`tokoya-*.zip`をダウンロードします。
2. Blenderの`Edit > Preferences > Extensions`を開きます。
3. メニューから`Install from Disk`を選び、ZIPを指定します。
4. 3D ViewのNパネルに`Tokoya`タブが表示されます。

## 基本操作

1. 空のHair Curvesオブジェクトを作り、`Hair`へ設定します。
2. `Body`へアニメーション追従対象兼コライダーのMeshを設定します。
3. `Create Head Mask`で白いペイント用メッシュを作ります。
4. Texture Paintで毛を生やす範囲を黒または灰色で塗ります。
5. `Plant Hair`で植毛します。
6. `Settle Hair Back`で背中方向へ初期整形します。
7. 必要に応じてCutter Meshを指定し、`Mesh Shrink`で切りそろえます。

## Natural Root Spacing

`Max Length`から全ストランド共通の点数を選びます。

```text
points = clamp(9 + floor((Max Length cm - 20) / 10), 9, 13)
```

黒い最大長の毛を基準に、根元2セグメントは全ストランドで同じ長さに揃えます。
灰色マスクで短く生えた毛や`Mesh Shrink`で短く切られた毛は、その共通Root
Zoneを保ったまま残りを均等割りします。Root Zoneより短い毛だけは、全体を
その長さへ圧縮します。

これにより、長い毛と短い毛が混在しても頭皮付近の関節位置が揃い、根元の流れが
乱れにくくなります。

## マスクの意味

```text
毛の長さ = (255 - 画素値) / 255 × Max Length
```

- 白（255）：0 cm
- 灰色：約半分の長さ
- 黒（0）：最大長

## Settle Hair Back

Bodyから穴埋め済みCollider Proxyを自動作成し、Clothesが指定されていれば同時にBVHへ入れます。頭頂部のカーブを保ちながら、下側のロングヘアを背中方向と下方向へ整えるCPU BVH初期整形です。

Surface DeformなどのモディファイアがあるHair Curvesでは、表示されているevaluated world座標で整髪と衝突判定を行い、モディファイアoffsetを差し引いてCurvesの元データへ書き戻します。

既知の制限として、Body用Collider Proxyは穴埋め済みの閉じた判定形状を作るため、耳の突起を一部除去します。そのため耳まわりだけは実Bodyと衝突形状が完全一致せず、軽いめり込みや手直しが残ることがあります。

Head MaskはBody表面から1 mm外側に生成されます。

## ライセンス

[MIT License](LICENSE)
