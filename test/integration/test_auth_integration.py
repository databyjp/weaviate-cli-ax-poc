import pytest
import weaviate
from weaviate.users.users import UserDB

from weaviate_cli.managers.collection_manager import CollectionManager
from weaviate_cli.managers.config_manager import ConfigManager
from weaviate_cli.managers.user_manager import UserManager


@pytest.fixture
def client() -> weaviate.WeaviateClient:
    config = ConfigManager()
    return config.get_client()


@pytest.fixture
def collection_manager(client: weaviate.WeaviateClient) -> CollectionManager:
    return CollectionManager(client)


@pytest.fixture
def user_manager(client: weaviate.WeaviateClient) -> UserManager:
    return UserManager(client)


def test_user_lifecycle(user_manager: UserManager):
    user_name = "test_user"
    try:
        # Create user
        api_key = user_manager.create_user(user_name=user_name)
        assert user_name in [user.user_id for user in user_manager.get_all_users()]
        assert api_key is not None

        # Update user
        new_api_key = user_manager.update_user(user_name=user_name, rotate_api_key=True)
        assert new_api_key is not None
        assert new_api_key != api_key

        # Deactivate user
        user_manager.update_user(user_name=user_name, deactivate=True)
        user = user_manager.get_user(user_name=user_name)
        assert isinstance(user, UserDB)
        assert not user.active

        # Activate user
        user_manager.update_user(user_name=user_name, activate=True)
        user = user_manager.get_user(user_name=user_name)
        assert isinstance(user, UserDB)
        assert user.active

        # Print user
        user_manager.print_user(user=user_name)

    finally:
        # Delete user
        user_manager.delete_user(user_name=user_name)
        assert user_name not in [user.user_id for user in user_manager.get_all_users()]
