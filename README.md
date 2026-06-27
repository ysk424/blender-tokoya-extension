# Tokoya

Tokoya（床屋、英語では *barber*）は、Blender 5.1用のヘアースタイリング拡張です。グレースケールの頭皮マスクから毛を植え、Taichi XPBDで自然に垂らし、メッシュで切りそろえます。

## 主な機能

- 白＝0 cm、黒＝最大長のUVペイントマスク
- 4,000本を既定値とする面積一様な植毛
- 長さに応じて9～13点を自動選択するストランド
- 根元2セグメントを最長毛基準で揃えるNatural Root Spacing
- CUDA（既定）、Vulkan、CPUバックエンド
- NVIDIA WarpによるCUDA Body衝突のバッチ処理
- ワールド座標BVH、点の連続衝突判定、セグメント衝突拘束
- `Mesh Shrink`による平面・球などを使ったカット
- `Urchin Reset`による直毛状態への復帰

セルフコリジョンは実装していません。

## 必要環境

- Blender 5.1以降
- Windows x64
- Pythonパッケージ `taichi`
- NVIDIA Warp（Blender 5.1同梱版を使用）
- CUDA利用時は対応するNVIDIA GPUとドライバー

TaichiはBlenderが使用するPython 3.13環境から参照できるユーザーsite-packagesへインストールしてください。

CUDA選択時は、点CCD・近傍投影・全ストランド区間のBody衝突をNVIDIA
WarpでGPUバッチ処理します。Warpを利用できない場合、またはVulkan/CPU選択時は
従来のBlender BVH処理へ自動的にフォールバックします。初回実行時のみWarp
カーネルのコンパイル時間が発生します。

## インストール

1. [Releases](../../releases)から最新の`tokoya-*.zip`をダウンロードします。
2. Blenderの`Edit > Preferences > Extensions`を開きます。
3. メニューから`Install from Disk`を選び、ZIPを指定します。
4. 3D ViewのNパネルに`Tokoya`タブが表示されます。

## 基本操作

1. 空のHair Curvesオブジェクトを作り、対象BodyへSurface設定します。
2. `Body`へアニメーション追従対象兼コライダーのMeshを設定します。
3. `Create Head Mask`で白いペイント用メッシュを作ります。
4. Texture Paintで毛を生やす範囲を黒または灰色で塗ります。
5. `Plant Hair`で植毛します。
6. `Simulate`で自然に垂らします。
7. 必要に応じてCutter Meshを指定し、`Mesh Shrink`で切りそろえます。

`Gravity`はX/Y/Zを自由に設定できます。既定値は`(0, 0, -9.81)`です。
長い髪を後ろへ誘導する場合は、最初の`Simulate`だけYをプラスにし、
形が整った後で通常の下向き重力へ戻せます。

時間刻みにはBlenderのFPSとFPS Baseを使用します。

```text
1フレームの秒数 = FPS Base / FPS
```

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

## 衝突処理

Bodyの評価済み形状からワールド座標BVHを構築します。各サブステップで点の移動経路と各ストランド区間を検査し、Body表面から0.5 mm外側へ拘束します。衝突補正量は速度へ変換せず、内向き法線速度だけを除去します。

Head MaskはBody表面から1 mm外側に生成されます。

## ライセンス

[MIT License](LICENSE)
