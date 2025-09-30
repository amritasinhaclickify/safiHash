// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract CoopTrust {
    address public admin;
    event TrustScoreUpdated(uint256 indexed user_id, uint256 indexed group_id, uint256 score_x100, uint256 timestamp, string note);

    modifier onlyAdmin() { require(msg.sender == admin, "only admin"); _; }

    constructor(address _admin) { admin = _admin; }

    function setTrustScore(uint256 user_id, uint256 group_id, uint256 score_x100, string calldata note) external onlyAdmin {
        emit TrustScoreUpdated(user_id, group_id, score_x100, block.timestamp, note);
    }

    function updateAdmin(address _new) external onlyAdmin { admin = _new; }
}
