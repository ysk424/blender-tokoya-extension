# Tokoya

Tokoya（床屋、英語では *barber*）は、Blender 5.1用の静的ヘアースタイリング拡張です。グレースケールの頭皮マスクから毛を植え、Taichi XPBDで自然に垂らし、メッシュで切りそろえます。

## 主な機能

- 白＝0 cm、黒＝最大長のUVペイントマスク
- 4,000本を既定値とする面積一様な植毛
- 根元が密で毛先ほど疎い、9点・8関節のストランド
- CUDA（既定）、Vulkan、CPUバックエンド
- ワールド座標BVH、点の連続衝突判定、セグメント衝突拘束
- `Mesh Shrink`による平面・球などを使ったカット
- `Urchin Reset`による直毛状態への復帰

セルフコリジョンは実装していません。

## 必要環境

- Blender 5.1以降
- Windows x64
- Pythonパッケージ `taichi`
- CUDA利用時は対応するNVIDIA GPUとドライバー

TaichiはBlenderが使用するPython 3.13環境から参照できるユーザーsite-packagesへインストールしてください。

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

長さを変更する場合は`Hair Remove`で毛だけを削除し、`Max Length`を変更して再植毛します。

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
