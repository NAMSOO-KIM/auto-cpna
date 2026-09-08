from autocpna.media_gen.openai_image_generator import _nearest_supported_size


def test_square_ratio_maps_to_square():
    assert _nearest_supported_size(1080, 1080) == "1024x1024"


def test_tall_ratio_maps_to_portrait():
    assert _nearest_supported_size(1080, 1920) == "1024x1536"  # 인스타 스토리


def test_wide_ratio_maps_to_landscape():
    assert _nearest_supported_size(1920, 1080) == "1536x1024"


def test_instagram_feed_ratio_maps_to_portrait():
    assert _nearest_supported_size(1080, 1350) == "1024x1536"  # 인스타 피드(4:5)
